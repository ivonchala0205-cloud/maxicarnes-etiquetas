-- Maxi Carnes: ejecutar en SQL Editor de un proyecto Supabase NUEVO.
-- No colocar claves ni contraseñas en GitHub.
create table if not exists public.municipios (
  id bigint generated always as identity primary key,
  nombre text not null unique,
  token_hash text unique,
  activo boolean not null default true
);
create table if not exists public.clientes (
  id bigint generated always as identity primary key,
  municipio_id bigint not null references public.municipios(id),
  nombre text not null,
  activo boolean not null default true,
  unique(municipio_id, nombre)
);
create table if not exists public.productos (
  id bigint generated always as identity primary key,
  nombre text not null unique,
  activo boolean not null default true
);
create table if not exists public.semanas (
  id bigint generated always as identity primary key,
  fecha_inicio date not null unique,
  fecha_beneficio date,
  lote text,
  abierta boolean not null default false,
  creada_en timestamptz not null default now()
);
create table if not exists public.pedidos (
  id bigint generated always as identity primary key,
  semana_id bigint not null references public.semanas(id),
  municipio_id bigint not null references public.municipios(id),
  estado text not null default 'enviado' check (estado in ('enviado','revisado','impreso')),
  enviado_en timestamptz not null default now(),
  unique(semana_id, municipio_id)
);
create table if not exists public.detalles_pedido (
  id bigint generated always as identity primary key,
  pedido_id bigint not null references public.pedidos(id) on delete cascade,
  cliente_id bigint not null references public.clientes(id),
  producto_id bigint not null references public.productos(id),
  gramos integer not null check (gramos > 0),
  capacidad_especial_gramos integer check (capacidad_especial_gramos > 0),
  aprobado_especial boolean not null default false
);
-- Ninguna tabla es accesible por claves anónimas.
alter table public.municipios enable row level security;
alter table public.clientes enable row level security;
alter table public.productos enable row level security;
alter table public.semanas enable row level security;
alter table public.pedidos enable row level security;
alter table public.detalles_pedido enable row level security;
-- Sin políticas: solo la clave secreta de servidor (service_role) puede operar.
-- Guardarla EXCLUSIVAMENTE en Streamlit Secrets, nunca en GitHub ni navegador.
