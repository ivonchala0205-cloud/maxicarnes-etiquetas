"""Pruebas sin credenciales ni cambios en pedidos reales."""
import ast
import unittest
from datetime import date, datetime, timedelta
from io import BytesIO
from pathlib import Path
from zoneinfo import ZoneInfo
from pypdf import PdfReader
from plantilla_etiqueta import pdf_etiquetas_diseno
from empaque import distribuir_por_destino


class FlujoEtiquetas(unittest.TestCase):
    def setUp(self):
        self.meta = {'numero_pedido': 'P1', 'fecha_beneficio': '2026-11-17',
                     'lote': 'L1', 'nit': '', 'fecha_empaque': None}
        self.pedido = {'estado': 'enviado'}
        self.calls = []
        tree = ast.parse(Path('app.py').read_text(encoding='utf-8'))
        names = {'datos_etiqueta_guardados', 'guardar_datos_etiqueta',
                 'asegurar_fecha_empaque', 'confirmar_pedidos_impresos', 'generar_pdf_pedidos'}
        subset = ast.Module(body=[n for n in tree.body if isinstance(n, ast.FunctionDef)
                                  and n.name in names], type_ignores=[])
        self.env = dict(date=date, datetime=datetime, timedelta=timedelta, ZoneInfo=ZoneInfo,
                        BytesIO=BytesIO, api_supabase=self.api, DIRECCION='Tenjo',
                        pdf_etiquetas_diseno=pdf_etiquetas_diseno,
                        consultar_pedido_por_numero=lambda n: (self.pedido, self.lineas()))
        exec(compile(subset, 'app.py', 'exec'), self.env)

    @staticmethod
    def lineas():
        return [{'Producto': 'CARNE MOLIDA', 'Municipio': 'Sibaté',
                 'Cliente': 'Institución de prueba', 'Bolsas': [2000, 2750]}]

    def api(self, tabla, metodo='GET', datos=None, parametros=None):
        self.calls.append((tabla, metodo, datos, parametros))
        if tabla == 'datos_etiqueta_pedido':
            if metodo == 'PATCH':
                if parametros.get('fecha_empaque') != 'is.null' or not self.meta['fecha_empaque']:
                    self.meta.update(datos)
            return [dict(self.meta)]
        if tabla == 'pedidos' and metodo == 'PATCH':
            self.pedido.update(datos)
            return [dict(self.pedido)]
        raise AssertionError((tabla, metodo))

    def test_first_generation_and_pdf(self):
        pdf, pages = self.env['generar_pdf_pedidos'](['P1'])
        expected = datetime.now(ZoneInfo('America/Bogota')).date() + timedelta(days=1)
        self.assertEqual(self.meta['fecha_empaque'], expected.isoformat())
        reader = PdfReader(BytesIO(pdf))
        self.assertEqual(pages, 2)
        for page in reader.pages:
            text = page.extract_text()
            self.assertIn(expected.strftime('%d/%m/%Y'), text)
            self.assertIn((expected + timedelta(days=30)).strftime('%d/%m/%Y'), text)
            self.assertAlmostEqual(float(page.mediabox.width), 100 * 72 / 25.4, places=3)
        Path('output/pdf').mkdir(parents=True, exist_ok=True)
        Path('output/pdf/validacion_etiquetas.pdf').write_bytes(pdf)

    def test_reprint_keeps_original_dates(self):
        self.meta['fecha_empaque'] = '2026-01-31'
        self.pedido['estado'] = 'impreso'
        pdf, _ = self.env['generar_pdf_pedidos'](['P1'])
        text = PdfReader(BytesIO(pdf)).pages[0].extract_text()
        self.assertIn('31/01/2026', text)
        self.assertIn('02/03/2026', text)
        self.assertFalse(any(c[1] == 'PATCH' for c in self.calls))

    def test_legacy_reprint_requires_original_date(self):
        self.pedido['estado'] = 'impreso'
        with self.assertRaisesRegex(ValueError, 'original'):
            self.env['generar_pdf_pedidos'](['P1'])
        self.assertFalse(any(c[1] == 'PATCH' for c in self.calls))

    def test_benefit_date_cannot_change_after_generation(self):
        self.meta['fecha_empaque'] = '2026-11-18'
        with self.assertRaises(ValueError):
            self.env['guardar_datos_etiqueta']('P1', date(2026, 11, 19), 'L2', '')
        self.env['guardar_datos_etiqueta']('P1', date(2026, 11, 17), 'L2', '')
        self.assertEqual(self.meta['fecha_empaque'], '2026-11-18')

    def test_confirmation_and_retry(self):
        self.env['confirmar_pedidos_impresos'](['P1'])
        self.env['confirmar_pedidos_impresos'](['P1'])
        self.assertEqual(self.pedido['estado'], 'impreso')
        self.assertTrue(all(c[2] == {'estado': 'impreso'} for c in self.calls))

    def test_confirmation_rejects_zero_rows(self):
        self.env['api_supabase'] = lambda *a, **kw: []
        with self.assertRaisesRegex(ValueError, 'no confirmó'):
            self.env['confirmar_pedidos_impresos'](['inexistente'])

    def test_concurrent_generation_uses_winning_date(self):
        original_api = self.api
        def concurrent(tabla, metodo='GET', datos=None, parametros=None):
            if metodo == 'PATCH':
                self.meta['fecha_empaque'] = '2026-11-18'
            return original_api(tabla, metodo, datos, parametros)
        self.env['api_supabase'] = concurrent
        result = self.env['asegurar_fecha_empaque']('P1', self.pedido, dict(self.meta))
        self.assertEqual(result, date(2026, 11, 18))

    def test_packaging_regression_and_partial_numbering(self):
        self.assertEqual(distribuir_por_destino('28.750', 'Gama', 'GOULASH'), [4000]*6+[4750])
        self.assertEqual(distribuir_por_destino('4.750', 'Sibaté', 'CARNE MOLIDA'), [2000,2750])
        line = dict(self.lineas()[0], Bolsas=[2750], **{'Número bolsa original': 2, 'Total bolsas original': 2})
        pdf = pdf_etiquetas_diseno([line], fecha_empaque=date(2026, 12, 31))
        text = PdfReader(BytesIO(pdf)).pages[0].extract_text()
        self.assertIn('BOLSA 2 DE 2', text)
        self.assertIn('30/01/2027', text)


if __name__ == '__main__':
    unittest.main(verbosity=2)
