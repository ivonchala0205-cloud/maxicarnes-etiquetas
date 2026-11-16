-- Ejecutar una vez en SQL Editor de Supabase.
-- Almacena datos editables para reimpresiones sin volver a diligenciarlos.
create table if not exists public.datos_etiqueta_pedido (
 numero_pedido text primary key,
 fecha_beneficio date not null,
 lote text not null,
 nit text,
 actualizado_en timestamptz not null default now()
);
create or replace function public.actualizar_fecha_datos_etiqueta()
returns trigger language plpgsql as $$
begin new.actualizado_en = now(); return new; end $$;
drop trigger if exists trg_fecha_datos_etiqueta on public.datos_etiqueta_pedido;
create trigger trg_fecha_datos_etiqueta before update on public.datos_etiqueta_pedido
for each row execute function public.actualizar_fecha_datos_etiqueta();
-- Acceso mediante clave secreta del servidor Streamlit, nunca desde el navegador.
alter table public.datos_etiqueta_pedido enable row level security;
