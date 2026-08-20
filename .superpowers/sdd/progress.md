# SDD Progress — Reset de Senha por Usuário ou Email
Plan: docs/superpowers/plans/2026-06-22-password-reset-by-email.md
Branch: main
Started: 2026-06-22

## Tasks
- [x] Task 1: _index_exists + migração UNIQUE em users.email
- [x] Task 2: Rota forgot_password aceita username ou email
- [x] Task 3: Template forgot_password.html atualizado

Task 1: complete (commits 0cd244a..0ce36f0, review clean — 3 Minor achados de estilo, não bloqueantes)
Task 2: complete (commits 0ce36f0..14d0a59, review clean — 1 Minor pré-existente: datetime.utcnow() deprecated)
Task 3: complete (commits 14d0a59..03ffc04, review clean — zero achados)
Fix Important: conn.commit() adicionado na migração UNIQUE (commit 63905ce)
Revisão final: Aprovado para merge (56 testes passing, sem Critical/Important abertos)

# SDD Progress — Gestão de Eventos + Tema Menina/Menino
Plan: docs/superpowers/plans/2026-06-30-eventos-e-tema.md
Branch: main
Started: 2026-06-30

## Tasks
- [x] Task 1: Funções de repo para eventos
- [ ] Task 2: Rotas de gestão de eventos + modificar respostas
- [ ] Task 3: Templates — admin_eventos.html + seletor de evento
- [ ] Task 4: Repo — set_event_theme e get_event_theme
- [ ] Task 5: Rota POST /admin/set_tema
- [ ] Task 6: Frontend — botões de tema e backgrounds dinâmicos

Task 1: complete (commits 53e7e25..74ac818, review clean — 2 Minor non-blocking)
Task 2: complete (commits 74ac818..6262c8e, review clean — 3 Minor: missing b"Meus Eventos" assertion in test, weak content assertions, _eventos_db missing return)
Task 3: complete (commits 6262c8e..c1dea2c, review clean — 3 Minor: dead JS, css reformat noise, btn-outline-primary vs light)
Task 4: complete (commits c1dea2c..0b0099c, review clean — zero findings)
Task 5: complete (commits 0b0099c..bc89dce, review clean — 4 Low: direct SQL in set_tema [plan-mandated], dead guard, misleading test name, redundant import)
Task 6: complete (commits bc89dce..b334cdc, fix: body class vazio → conditional attribute, review clean)

# SDD Progress — Redesign Visual Fase 2 (Autenticação)
Plan: docs/superpowers/plans/2026-07-07-auth-redesign.md
Branch: main
Started: 2026-07-07

## Tasks
- [x] Task 1: Classes de autenticação em admin.css
- [x] Task 2: Migrar login.html
- [x] Task 3: Migrar signup.html
- [x] Task 4: Migrar verify_email_sent.html
- [x] Task 5: Migrar resend_verification.html
- [x] Task 6: Migrar forgot_password.html
- [x] Task 7: Migrar reset_password.html
- [x] Task 8: Migrar change_password.html
- [x] Task 9: Verificação final

Task 1: complete (commits 3be4a36..d22b3d8, review clean — zero achados)
Task 2: complete (commits d22b3d8..0e6b292, review clean — zero achados)
Task 3: complete (commits 0e6b292..383b9cb, review clean — zero achados)
Task 4: complete (commits 383b9cb..3b0166c, review clean — zero achados)
Task 5: complete (commits 3b0166c..7e45004, review clean — código aprovado; nota de processo: implementador rodou `docker compose run backend-test` com pip install (proibido/sem internet) em vez do comando docker mandatado; controller reverificou independentemente com o comando correto: 161 passed, 38 deselected, limpo)
Task 6: complete (commits 7e45004..d91f376, review clean — zero achados)
Task 7: complete (commits d91f376..99ff17e, review clean — zero achados)
Task 8: complete (commits 99ff17e..dab450f, review clean — zero achados)
Task 9: complete (suite completa: 161 passed, 38 deselected; checagem HTTP automatizada das 7 telas confirmou classes .auth-page/.auth-brand/.auth-box* presentes e zero gradiente antigo remanescente; checagem visual manual em navegador não realizada pelo controller — recomendado smoke test como no Fase 1)
Revisão final (whole-branch, modelo opus): Aprovado para merge — zero Critical/Important. 3 Minor (todos cosméticos, já conformes ao plano/mockup): (1) verde do botão Signup é #198754 do Bootstrap .btn-success, não o #16a34a citado na spec — decisão do próprio plano; (2) links secundários (Esqueci senha/Voltar ao login/etc.) mudam de cinza (.text-muted) para azul padrão de link — intencional, confirmar no mockup; (3) login.html normalizado de CRLF para LF (inofensivo). Nenhuma ação obrigatória antes do merge.
Checagem visual manual (smoke test via Claude no Chrome): todos os 7 passos aprovados ✅ — incluindo /change_password no reteste com conta role=member correta (a primeira tentativa usou conta tenant_admin, que a lógica de force_password_change ignora de propósito — não é bug do redesign). Fase 2 encerrada.

# SDD Progress — Redesign Visual Fase 3 (Convite público)
Plan: docs/superpowers/plans/2026-07-07-invite-redesign.md
Branch: main
Started: 2026-07-07

## Tasks
- [x] Task 1: Atualizar cores em invite.html
- [x] Task 2: Verificação final

Task 1: complete (commits dab450f..59311fc, review clean — zero achados)
Task 2: complete (suite: 161 passed, 38 deselected; checagem HTTP automatizada confirmou #f4f5f7/#1d4ed8/#dc2626/border presentes e #fde2e7/#2196f3/#e53935 ausentes na página sem tema; tema Menina confirmado intacto (body.theme-girl + gradiente original #fce4ec/#f8bbd0 inalterado); fluxo de resposta (POST yes + observação) testado e funcionando; dados de teste limpos)
Revisão final (whole-branch, modelo opus): Aprovado para merge — zero Critical/Important. 2 Minor cosméticos: (1) comentário desatualizado "/* agora só rosa */" em invite.html:82 — corrigido no commit f5cc184 (removido, era stale narration); (2) cor cinza #e5e7eb duplicada como literal em --bg-soft e no border do .invite-container, sem variável compartilhada — trade-off documentado, sem ação necessária (não podem ser a mesma variável pois --bg-soft precisa mudar com o tema, o border não). Decisão do plano sobre --bg-soft (não estava na spec original) avaliada e confirmada correta pelo revisor. Fase 3 encerrada — redesign visual completo (Fases 1, 2 e 3).

# SDD Progress — Super-admin como Role no Banco (Fase 1)
Plan: docs/superpowers/plans/2026-07-21-superadmin-role-fase1.md
Branch: main
Started: 2026-07-21

## Tasks
- [x] Task 1: Migration 0006 — role super_admin + tenant reservado
- [x] Task 2: repo.py — tenant reservado e exclusão da listagem
- [x] Task 3: Autorização baseada em role
- [x] Task 4: Redirect no login + bloqueio de rotas de tenant
- [x] Task 5: Comando flask create-superadmin
- [x] Task 6: Documentação + smoke test manual

Task 1: complete (commits 71b2e36..319beec, review clean — zero Critical/Important; 3 Minor todas herdadas do brief, não do implementador; controller confirmou suite unitária 163 passed, 45 deselected)

Task 2: complete (commits 319beec..a3ecb2f, review clean — zero Critical/Important; 2 Minor plan-mandated: teste unitário só verifica texto SQL, não comportamento real de filtro; string "migration 0006" hardcoded na mensagem de erro)

Task 3: complete (commits a3ecb2f..b7a932c, review clean — zero Critical/Important; 1 Minor pré-existente de estilo. Nota: brief tinha um `with client:` que colide com Flask 3.0.3 (client fixture já abre seu próprio with) — implementador corrigiu removendo o with redundante, revisor verificou contra o source do Flask e confirmou correção legítima, sem perda de cobertura do teste)

Task 4: complete (commits b7a932c..7094e4f, review clean — zero Critical/Important; ordem dos before_request hooks verificada diretamente no diff pelo revisor; 2 Minor plan-mandated: bloqueio abrange toda rota fora da allowlist [não só "tenant"], request.endpoint=None também redireciona — ambos herdados do brief/padrão já existente em force_password_change)

Task 5: complete (commits 7094e4f..2244321, review clean após 1 rodada de fix — Important corrigido: ramo com SMTP configurado do CLI não tinha cobertura de teste [reviewer pediu verificação nomeada, gap real confirmado]; fix adicionou 1 teste com 5 qresults ordenados + mock de enqueue_email; re-review confirmou sequência de mocks bate com a ordem real de conn.execute em repo.py. 2 Minor não bloqueantes registrados para a revisão final: username "superadmin" hardcoded poderia colidir em re-provisionamento futuro com email diferente [fora de escopo da Fase 1]; import de click quebra ordem alfabética do bloco de imports [cosmético])

Task 6: complete (commits 2244321..76b8b11, review clean — zero Critical/Important. Smoke test manual via curl real (login → redirect /superadmin → force /change_password → troca de senha → bloqueio de /admin/respostas e /admin/eventos → /superadmin 200 sem listar "Comemore+ System") totalmente verificado, evidenciado com status codes e greps reais, sem bugs encontrados. 2 Minor resolvidos pelo controller após a review: nota residual no README sobre checagem por email corrigida (commit 2b13e7f); contagem de testes desatualizada no CLAUDE.md corrigida 148→173/33→45 (commit 76b8b11). Suite completa confirmada: 173 unit passed + 45 integration passed, zero regressão.

Todas as 6 tasks da Fase 1 completas. Pronta para revisão final de branch inteiro.

Revisão final (whole-branch, modelo opus): Aprovado para merge (Ready to merge: Yes) — zero Critical/Important. 3 Minor: (1) CLI create-superadmin não é atômico entre as duas conexões — se o INSERT do token/envio de email falhar após o commit da conta, reprovisionar reporta "já existe" sem reenviar o convite (recuperável via /forgot_password, mas não óbvio); (2) bloco de emissão de token de convite duplicado em 3 call sites agora (add member, reset_senha, create-superadmin) — Task 5 estendeu duplicação pré-existente em vez de extrair helper; (3) string "Comemore+ System" definida em 3 lugares independentes (migration, repo.py, testes) sem constante compartilhada. Todos os 3 marcados como candidatos naturais pra Fase 2 (que já mexe no CLI de qualquer forma). 2 observações pré-existentes não relacionadas a esta branch (pytest.mark.integration não registrado; TTL do convite documentado como 72h no CLAUDE.md vs 1h real no código). Suite: 173 unit passed + 45 integration passed.

Fase 1 encerrada — pronta pra decisão de merge/próximos passos com o usuário.

# SDD Progress — Débitos Técnicos da Fase 1 (Super-admin)
Plan: docs/superpowers/plans/2026-08-19-superadmin-debitos-tecnicos.md
Branch: main
Started: 2026-08-19

## Tasks
- [x] Task 1: repo.py — create_password_reset_token + SYSTEM_TENANT_NAME
- [ ] Task 2: add_usuario e reset_senha_usuario usam o helper
- [ ] Task 3: create-superadmin atômico + reenvio de convite incompleto
- [ ] Task 4: Verificação final

Task 1: complete (commits 76b8b11..683b61b, review clean — zero Critical/Important/Minor. 43/43 testes de test_repo.py passando)

Task 2: complete (commits 683b61b..7a658e3, review clean — zero Critical/Important; 1 Minor observacional: os outros 2 call sites que ainda duplicam o bloco (forgot_password e create-superadmin) seguem fora de escopo por design até a Task 3. 177 unit tests passando, novo teste cobre o branch de convite de reset_senha_usuario que não tinha cobertura antes)

Task 3: complete (commits 7a658e3..281d668, review clean — zero Critical/Important. 2 Minor não bloqueantes: (1) reenviar convite não invalida o token anterior ainda válido, gerando acúmulo de tokens em reprovisionamentos repetidos — padrão pré-existente em password_reset_tokens, fora de escopo; (2) os 2 novos testes usam commit.assert_called() em vez de assert_called_once() (herdado verbatim do brief), não pegaria uma regressão de double-commit hipotética. Atomicidade confirmada: usuário+token na mesma transação/commit único; reenvio de convite quando must_change_password=True testado e funcionando; os 5 testes pré-existentes permaneceram inalterados. Suíte completa: 179 passed, 45 deselected)

Task 4: complete (unit suite run: 179 passed, 45 deselected; grep sanidade: zero INSERT password_reset_tokens outside forgot_password (1 ocorrência esperada em app.py:550), zero literal "Comemore+ System" solto em repo.py (constante SYSTEM_TENANT_NAME em repo.py:105 confirmada); CLAUDE.md atualizado: test count 173→179 unit; progress.md section adicionado com commits 683b61b..281d668; nenhuma regressão detectada, branch pronta para merge)

Todas as 4 tasks completas. Débitos técnicos da Fase 1 fechados.
