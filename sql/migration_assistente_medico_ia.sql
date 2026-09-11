-- Módulo 8 — Assistente Médico de IA: analisa o que já está arquivado
-- no Módulo 7 (prontuário/exames) e ajuda o médico na avaliação.
-- Sempre assistivo — o médico decide, nunca o sistema.

create table if not exists analises_medico_ia (
    id uuid primary key default uuid_generate_v4(),
    medico_id uuid not null references medicos(id),
    paciente_nome text not null,

    entrada_clinica text not null,        -- o que foi mandado pra IA (criptografado)
    resposta_ia text not null,             -- resposta estruturada (criptografada)
    fontes_consultadas text,               -- JSON com PMIDs/artigos usados, se houve busca

    modelo_ia text not null,               -- ex: 'claude-sonnet-4-6' — registra qual modelo gerou, p/ auditoria
    alertas_backend text,                  -- JSON com alertas da camada de segurança determinística (não-IA)
    avisos_seguranca text,                 -- JSON com o que a camada de segurança pós-resposta corrigiu/bloqueou

    feedback_medico text check (feedback_medico in ('concordo', 'parcial', 'discordo', 'corrigir')),
    feedback_texto text,                   -- se o médico corrigiu algo, o texto da correção (criptografado)
    feedback_em timestamptz,

    criado_em timestamptz not null default now()
);

create index if not exists idx_analises_medico_ia_medico_paciente
    on analises_medico_ia(medico_id, paciente_nome);

alter table analises_medico_ia enable row level security;
