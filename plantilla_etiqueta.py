"""Plantilla de etiqueta MaxiCarnes 100 x 100 mm, una página por bolsa."""
from io import BytesIO
from datetime import date, timedelta
import base64
from reportlab.pdfgen import canvas
from reportlab.lib.units import mm
from reportlab.lib.utils import ImageReader

LOGO_B64 = "iVBORw0KGgoAAAANSUhEUgAAAQQAAAB4AQAAAAA85LGpAAAFUUlEQVR42s2Xv28jxxXHPzNcixv4fFwkQaBCMBeu3ASRuyvs4wYIkCvVBAhcCYaBpFSpQjDnfiBmZbtLE8DKf5AuQZAEqzsmviKI5e5cGFgKB0SIjWAY0/ZQGO5LMbvkUlpKLlJkCmIx/OK973vv+97MKOH6NdXctP4/EXMVX49YxMzjaxHjrrh5dgmhGhlbvFDC/EW/OWOzu0D3z5eNyGqdiBQd8V1pLttEdMWCErMRUfYFoGcHmxB+GDiW3U0IJxaA/skaohHLnFMAnv/IbMjYf8hDWt473hDtR3Xyeu9u8PJ0mbk3N9WltrF4f4OXflnv7QzavbBEfHna2I2u+ABm43Ye6UoGOzfq9GetiLKx+9zcZONf+U2IxV4rolh9L+7c2FG/aUeo1ec/2hDesorgnxu8rPrgC9OGcI2s6rwFEcE20BEPLIo2G54t4IiOgfKgRR9eieT0RcQCH7d0g2f11TM/bVVQzb9Dsr/TGm1ogvsxhuS0hUdJL/hlWPTda61eZgAJfJC0d4NiAcyBWWzptmc9hRGwiFx7vxioun+o7J1WHqACg+NhsqqzvlpZj80aZb7aL71O7nbb+6WKcZddH6tWfVTzOicuu1utNkILd2FLcK4NoWtLiqydh6pogCmwrTnN65/MclmFKq3D7QCkM/L1rLtQeAf0gwKOWFdhEXWCQmBYQ5cIJcB9+cnrACdZx4OSRbQaWlNERJRMKpkNRTzDEtSaF9+tENXWQJoIDfhtGrqzrxeYRhY04Pabo7J4DFljimrArp0WT5QlJV5DTNZ09ghIGm418JhK5AASA7fYX8tpV8RKMayati89kY/WJr/EwKpUKUA9C+cZGspkWVjAZzS65fM9NPi02fhuvT2eocFlgeConhGNC8bzUxCxIjItt4ddEZEvJ1L2ViX49PdWEwRXpuIB/l3zqiI9Qgd9Wp+F06M4Wx/fGRrOAkEfVbF6lqhkOl7V8PAwkwz0GNIPDcAinc84QMMY0FPILgrYAYfJOYaZPS9ffnVZ5bMfTnF2eWr2ys+e/NYVg+/sfaLD2ClQZ1h3fHE6wt7d4WLmi4l58rtb+0seY0s8MQff/AHwr0gcOzSP6CzVFo0Ym8cS/BxmWGMZy3ajK3MY8QgmJICh88u3GMEU0EgCSHIGMX/627ugbFlGRPAripWNMpWklyhGwA8mEJNLEv6tECPKfkmwF2tgOkrluyFVtW7GkJqynwRSidwuX8beAzTKAs74zGdxmpFC5H1Kik/d7tKG1AI1QUMZZP7pj3013hygMP6PgiIFYkdWkD01qsrHUXCGM0lRXTEO4YgO+yYg3qjvHtXfkoTT+4jkOCDSdE4kmgxyKLiggBOc4ZYNiGQSA5FXPh2SgQOLxnChKx63wccAThIAy4nCAE65gFBuQFLGWMrYYCkwEDkIdDTQzUOjWZ+i4HEYN7E5bpxiduD77uBBchgNuuXWTvJEevbZO0q6y1PdDn3fHWzho/5Dd5vdTtlz8Tbv9JbnnEWnECsdp4s4IYOE75/vPkiWXgoRcXf6PSmHOUPcL6Tv7+IYLL3kIuLvDqsp/VBEpBw+LFndLk5ExIdL6aUrf80jBzphCnVc6+tE/w9eSdGNiHvXINS3fjVO00nGCQ/EzNPz2Tw9F3OJqTroGP5ufg3zA2/VwepSXCP0nSjje/K24esM+PlqSOvmOD82GtguC85ZXM1H/ZCLiZDs+ozJKaD3ryC6+XL0G/WMr0ybjaK6c6dBVZcQ58Dw/l9M1Rl8czmWxd484xX+yqOX9lQur159ncT7Cbw2uKeiW/txrHa3bfqt6/Jf67LDmpSXJyMAAAAASUVORK5CYII="
W = H = 100 * mm
M = 3.2 * mm
R = W-M

def texto(c, x, y, valor, tam=7, negrita=False, max_ancho=None):
    valor = str(valor or "")
    fuente = "Helvetica-Bold" if negrita else "Helvetica"
    while max_ancho and c.stringWidth(valor, fuente, tam) > max_ancho and tam > 4:
        tam -= .3
    c.setFont(fuente, tam)
    c.drawString(x, y, valor)

def caja(c, x, y, w, h, grosor=.6):
    c.setLineWidth(grosor)
    c.rect(x, y, w, h)

def pdf_etiquetas_diseno(lineas, numero_pedido="PRUEBA", lote="",
                         fecha_beneficio=None, fecha_empaque=None, nit="",
                         conservacion="Mantener refrigerado entre 0 °C y 4 °C",
                         instrucciones="Cocinar antes de consumir.",
                         direccion="Calle 3 # 12-74 Tenjo Cundinamarca",
                         invima="233DM"):
    if not lineas or not any(p.get("Bolsas") for p in lineas):
        raise ValueError("No hay etiquetas para generar")
    fecha_empaque = fecha_empaque or date.today()
    salida = BytesIO()
    c = canvas.Canvas(salida, pagesize=(W,H), pageCompression=1)
    logo = ImageReader(BytesIO(base64.b64decode(LOGO_B64)))
    for linea in lineas:
        for indice, gramos in enumerate(linea["Bolsas"], 1):
            caja(c, M, M, W-2*M, H-2*M, 1.5)
            c.drawImage(logo, 28*mm, 79*mm, width=44*mm, height=20*mm, preserveAspectRatio=True, mask='auto')
            c.line(6*mm, 85*mm, 25*mm, 85*mm)
            c.line(75*mm, 85*mm, 94*mm, 85*mm)
            # Título del producto
            caja(c, 5*mm, 66*mm, 90*mm, 12*mm, 1)
            producto = str(linea["Producto"]).upper()
            tam = 16
            while c.stringWidth(producto, "Helvetica-Bold", tam)>86*mm and tam>8: tam-=.5
            c.setFont("Helvetica-Bold",tam)
            c.drawCentredString(W/2, 70.1*mm, producto)
            # Municipio, cliente y NIT
            for y,etiqueta,valor in [(61,"MUNICIPIO",linea["Municipio"]),(56,"CLIENTE",linea["Cliente"]),(51,"NIT",nit)]:
                caja(c, 5*mm, y*mm, 90*mm, 5*mm)
                c.line(31*mm, y*mm, 31*mm, (y+5)*mm)
                texto(c, 7*mm,(y+1.4)*mm,etiqueta+":",7,True)
                texto(c, 33*mm,(y+1.4)*mm,valor or "—",7,False,60*mm)
            # Peso a la izquierda; fechas a la derecha
            caja(c,5*mm,30*mm,90*mm,21*mm)
            c.line(43*mm,30*mm,43*mm,51*mm)
            texto(c,9*mm,44*mm,"PESO NETO:",10,True)
            texto(c,8*mm,34*mm,f"{gramos:,}".replace(",","." )+" g",17,True,33*mm)
            fechas=[("FECHA DE BENEFICIO",fecha_beneficio.strftime("%d/%m/%Y") if fecha_beneficio else ""),
                    ("FECHA DE EMPAQUE",fecha_empaque.strftime("%d/%m/%Y")),
                    ("FECHA DE VENCIMIENTO",(fecha_empaque + timedelta(days=30)).strftime("%d/%m/%Y")),
                    ("LOTE",lote)]
            for j,(titulo,valor) in enumerate(fechas):
                y=(51-(j+1)*5.25)*mm
                if j: c.line(43*mm,y+5.25*mm,95*mm,y+5.25*mm)
                c.line(73*mm,y,73*mm,y+5.25*mm)
                texto(c,44*mm,y+1.7*mm,titulo+":",5.7,True,28*mm)
                texto(c,74*mm,y+1.7*mm,valor,6.2,False,20*mm)
            # Conservación e instrucciones
            caja(c,5*mm,16*mm,90*mm,14*mm)
            c.line(50*mm,16*mm,50*mm,30*mm)
            texto(c,7*mm,25*mm,"CONSERVACIÓN:",8,True)
            texto(c,7*mm,19*mm,conservacion,6.1,False,41*mm)
            texto(c,52*mm,25*mm,"INSTRUCCIONES DE USO:",7.3,True)
            texto(c,52*mm,19*mm,instrucciones,6.4,False,40*mm)
            # Pie, sin avisos entre paréntesis
            caja(c,5*mm,5*mm,90*mm,11*mm)
            c.line(65*mm,5*mm,65*mm,16*mm)
            texto(c,6*mm,12.6*mm,"PROCESADO Y EMPACADO POR:",7.3,True)
            texto(c,6*mm,9.4*mm,"MaxiCarnes H&M",7.5)
            texto(c,6*mm,6.6*mm,direccion,5.8,False,58*mm)
            texto(c,67*mm,12.6*mm,"CÓDIGO INVIMA:",7.1,True)
            texto(c,67*mm,8*mm,invima,11,True,26*mm)
            c.showPage()
    c.save()
    return salida.getvalue()
