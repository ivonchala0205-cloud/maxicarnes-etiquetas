"""Plantilla de etiqueta MaxiCarnes 100 x 100 mm, una página por bolsa."""
from io import BytesIO
from datetime import date, timedelta
import base64
from reportlab.pdfgen import canvas
from reportlab.lib.units import mm
from reportlab.lib.utils import ImageReader

LOGO_B64 = "iVBORw0KGgoAAAANSUhEUgAAAQQAAACDAQAAAABDsVhzAAAFWElEQVR42uWXz4vkRBTHP5VupqOMdtbTHIbtIOpNXMXDHtbtiIIePCj4B8xB8KgHDwpi1y6D2yfHo4LiIPoHePEg/sjuDjreBryJsNW9C44gTFoHrO5N8jxUkk53snoT1FySKl5937defd97FSX89TPz+Lvn32eREANcUs0l4p7f5RsRMUBHVp6kXLKBAfaBLKpWJ3WMVG6IWGiAVBgeARzSF4lrIHUMkRMRrUREdG8Fo7IYnIg4B4lq9YK2ZGwD9CVq9XLjZbGMRETE9Nu8/HzycjXIO21eNu3zoNy3ytuifvfmT+lRObihWyzUGOgWg+39NovPz7mzA+gcNy1u8f5D4JezXzQt7qFTZxc2LTaDBy0E5WxfNyMWf/XGbQZlENLhMh4l/eHgbLeGbFp0+lltEpW0nEv2jrA8jystp5/fHNUsbjbPRbyHLbZCzpte0oEZsBRX0sQ43dmCtFrnNzGuiOwtVT6xowbG6/Bi4X0WILttWp/chpGI5DAyZ4dNJfNpUG0jBtOS++rUZeUBHAVJS9QzCxyDRHDqqxYe10U0uPRXaX/QjOlzAETsA9LpL92UR567qasOPjJnGjz+AJbJaPIm083lVN9w67S10uWFfl/dJgvaYiq3HRUlOTBoiSmpX1Q0pe9QT4sNbtUpr1ocu53vrCZUncdeXk4kd+ARKICO23oJY+peDHERGG9JJVyt/CHwKqBAt/FwNVlERHQ5ndcySpwAXUIYtZYNk4KXijnvytRGLYcFxOvZGpt5vz6adYFF/7U638NFo0fZcythjqXRGy7JpM63l4zWa/LbK0uy8/66l2yLumBOo0YntAOZyc+1wlCrc86L3SHhg2rJD81uGotMRNVKWAPjOlDb4LjZs3ddwhdspV6KnIX4ME13KpSgodM8AOzl3K5mTc0iDYGZKbLsOI0aFhboTsvxvtXYdaYRxDBzsU6XiVPpYzKAMVx4LgHwfzzLZNC8bY3f87uV4pmseZm4IDzj4uFfu8Mtp9riUZdlzywsroHcy14R0lBXq3QdY3uYh+H8AgwiH7T0RuE41HiiNB4acjQXo+Nvp5ILSHexyE9GyWHGYisuMOZsa25eNjkmgC2bePcSfHn6in2p9HIut3AAaRgCzCC9C41OSlbpFJUyfjq0cQ7KTNEWYcakYrrLY3YUwCy9EAIHKr/vkbw75Ro4pvYwNeThYTC1OgL833gg39YHs24KHjmg6ao0shwUkcjS76M5YyDCIwIV8Gyy1KgEEOjHfEfBYwAn4RysRoKZ1YXMUrMX3ErReAQhJjp515uhq+NRdoen8vDZiwq8mmD8QsJpZMqWuwEemzMda0IDoKflaWn7LlkwADw6sQYTMc2WaHECZ7cPwsDFdMgl16wC41qW1buKBJ6M/ZhyQ2gO0hAOAT4Tppgo+pqNo0otV4mpxOWk82ZNheJUbHkPDQi574JrlS0wfDzGJEW2LaIUuIrmF950FrnL/0+yUAdorJ7jIn6sowKjLGMOZEbi9qajkkcaAszHX3Z38WM+lvtzDfDh4/tFPbVDGciV+AJpr2MHaS/pX+rLnt0mp+d6gx2JyHUjj+aDK3knHtrhdx+JpBc7ovvLWx/ZGa4pc0QWDbvReQs8+QI739Q6kCneqz2p3gnLimD6a5mt/pd/a/+URRbMfa6GarEgnrRj2KoFYXSbhfpVWZ4wIzTciFsxNpbf+zvrFhOlwrRTXTGATJV/qV0Q99mV+jU+BVH0XEa5VmtAfOAyz0N5l7Fr8VAWeIu1Rtet4XrVte8OMV0sG+6Obrv1pT3bk0yYz8wwHjX/kmrod/eiR4f/Ta3/CcSfL+37fPMwAAAAAElFTkSuQmCC"
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
