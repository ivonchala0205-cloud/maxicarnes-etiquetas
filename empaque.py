"""Reglas iniciales de empaque de Maxi Carnes. Cantidades en gramos."""
from decimal import Decimal, InvalidOperation


def convertir_a_gramos(kilos):
    """Convierte kg a gramos sin errores de redondeo binario."""
    try:
        cantidad = Decimal(str(kilos).replace(",", ".")) * 1000
    except InvalidOperation as exc:
        raise ValueError("Cantidad de kilos no válida") from exc
    if cantidad <= 0 or cantidad != cantidad.to_integral_value():
        raise ValueError("La cantidad debe ser positiva y expresarse en gramos enteros")
    return int(cantidad)


def distribuir_bolsas(kilos, capacidad_gramos=4000, tolerancia_gramos=999):
    """Bolsas estándar; si el resto es menor a 1 kg, se une a la última bolsa.

    Ejemplos (kg): 28.750 -> [4,4,4,4,4,4,4.750]; 5 -> [4,1];
    0.700 -> [0.700]. Las reglas se podrán configurar por producto y destino.
    """
    total = convertir_a_gramos(kilos)
    if capacidad_gramos <= 0 or tolerancia_gramos < 0:
        raise ValueError("Configuración de empaque no válida")
    completas, resto = divmod(total, capacidad_gramos)
    bolsas = [capacidad_gramos] * completas
    if resto:
        if bolsas and resto <= tolerancia_gramos:
            bolsas[-1] += resto
        else:
            bolsas.append(resto)
    assert sum(bolsas) == total
    return bolsas


if __name__ == "__main__":
    for pedido in ("0.700", "0.900", "4.999", "5.000", "28.750"):
        bolsas = distribuir_bolsas(pedido)
        print(f"{pedido} kg: {len(bolsas)} etiquetas -> "
              + ", ".join(f"{peso / 1000:.3f} kg" for peso in bolsas))
