"""Generación de archivos ZPL de prueba para etiquetas de 100 x 100 mm a 203 dpi."""
import unicodedata
from datetime import date

ANCHO = 800
ALTO = 800
EMPACADOR = "MaxiCarnes H&M"
DIRECCION = "Calle 3 # 12-74, Tenjo, Cundinamarca"
TELEFONO = "3223721832"
INSTRUCCIONES = "Producto que requiere coccion para su consumo"


def limpio(valor, maximo=75):
    texto = unicodedata.normalize("NFKD", str(valor or ""))
    texto = "".join(c for c in texto if not unicodedata.combining(c))
    texto = texto.replace("^", " ").replace("~", " ")
    texto = "".join(c for c in texto if 32 <= ord(c) <= 126)
    return " ".join(texto.split())[:maximo]


def campo(y, etiqueta, valor, alto=27, fuente=21):
    return (f"^FO20,{y}^A0N,{fuente},{fuente}^FD{limpio(etiqueta)}: {limpio(valor)}^FS\n"
            f"^FO15,{y+alto}^GB770,1,1^FS\n")


def generar_zpl(lineas, numero_pedido="PRUEBA", lote="", fecha_beneficio=None,
                nit="", conservacion="", fecha_empaque=None):
    """Una etiqueta por bolsa. No imprime automáticamente ni modifica estados."""
    fecha_empaque = fecha_empaque or date.today()
    salida = []
    for linea in lineas:
        for indice, gramos in enumerate(linea["Bolsas"], 1):
            z = ["^XA", "^CI27", "^PW800", "^LL800", "^LH0", "^PR3", "^MD10",
                 "^FO8,8^GB784,784,2^FS",
                 "^FO15,15^GB770,85,2^FS",
                 "^FO28,24^A0N,42,42^FDMaxiCarnes^FS",
                 "^FO30,68^A0N,19,19^FDDE COLOMBIA - ETIQUETA DE PRUEBA^FS"]
            z.append(campo(110, "Producto", linea["Producto"], 42, 26))
            z.append(campo(165, "Municipio", linea["Municipio"], 36, 23))
            z.append(campo(213, "Cliente", linea["Cliente"], 36, 22))
            z.append(campo(261, "NIT municipio", nit or "PENDIENTE", 36, 22))
            z.append("^FO15,309^GB770,76,2^FS")
            z.append(f"^FO28,322^A0N,38,38^FDPESO NETO: {gramos/1000:.3f} kg^FS")
            z.append(campo(394, "Pedido", numero_pedido, 33, 22))
            z.append(campo(439, "Bolsa", f"{indice} de {len(linea['Bolsas'])}", 33, 22))
            z.append(campo(484, "Lote", lote or "PENDIENTE", 33, 22))
            beneficio = fecha_beneficio.strftime("%d/%m/%Y") if fecha_beneficio else "PENDIENTE"
            z.append(campo(529, "Beneficio", beneficio, 33, 22))
            z.append(campo(574, "Empaque", fecha_empaque.strftime("%d/%m/%Y"), 33, 22))
            z.append("^FO20,620^A0N,19,19^FDConservacion: " + limpio(conservacion or "PENDIENTE") + "^FS")
            z.append("^FO20,645^A0N,19,19^FDProcesado y empacado por: " + limpio(EMPACADOR) + "^FS")
            z.append("^FO20,670^A0N,18,18^FD" + limpio(DIRECCION) + "^FS")
            z.append("^FO20,694^A0N,18,18^FDTel: " + TELEFONO + "^FS")
            z.append("^FO20,718^A0N,17,17^FD" + limpio(INSTRUCCIONES) + "^FS")
            z.append("^FO20,744^A0N,17,17^FDVencimiento e INVIMA: VALIDAR ANTES DE USO^FS")
            z.append("^XZ")
            salida.append("\n".join(z))
    if not salida:
        raise ValueError("No hay bolsas para generar etiquetas.")
    return ("\n".join(salida) + "\n").encode("ascii")
