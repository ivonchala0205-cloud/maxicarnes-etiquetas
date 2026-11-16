-- Ejecutar una sola vez en el editor SQL de Supabase.
ALTER TABLE public.datos_etiqueta_pedido
ADD COLUMN IF NOT EXISTS fecha_empaque DATE;
-- Las etiquetas anteriores deben revisarse y asignarles fecha de empaque real.
