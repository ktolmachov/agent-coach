# D11 Remediation Implementation Prompt

Самодостаточный master-prompt для реализации подтверждённых рекомендаций
архитектурного отчёта и его критической проверки. Промпт учитывает, что
исходный отчёт нельзя реализовывать буквально, а работы пересекают несколько
владельческих срезов.

Один запуск выполняет ровно один `WORK_PACKAGE`. После отчёта о продвижении
выбранного пакета агент обязан остановиться. Команда владельца
`Продолжи выполнение следующего пакета <путь-к-этому-prompt>` является
разрешением на следующий вычисленный offline-пакет и на техническую фиксацию
предыдущего `COMPLETE + PASS` checkpoint, если она ещё не сделана. Межсессионное
состояние передаётся через проверяемый status ledger, а не через память чата.

## Источники

- репозиторий: Git root, содержащий этот prompt, либо явно заданный
  `REPOSITORY_ROOT`;
- критическая проверка: необязательный внешний `AUDIT_REF`; отсутствие
  исходного файла не блокирует продолжение, потому что подтверждённые решения
  уже зафиксированы в этом prompt, плане, коде и тестах;
- источник истины по срезам: `docs/implementation_plan.md`;
- архитектурные границы: `docs/architecture.md`;
- агентный контракт: `AGENTS.md`;
- публичные команды: `README.md`, `CONTRIBUTING.md`;
- официальный контракт Structured Outputs:
  `https://developers.openai.com/api/docs/guides/structured-outputs`;
- возможности GPT-4.1 Mini:
  `https://developers.openai.com/api/docs/models/gpt-4.1-mini`.

## Запуск следующего пакета

Обычный межсессионный запуск не требует ручного заполнения параметров:

```text
Продолжи выполнение следующего пакета \
<REPOSITORY_ROOT>\docs\prompts\d11_remediation_implementation_prompt.md
```

Эта форма детерминированно означает:

```text
WORK_PACKAGE = RESUME
OWNER_APPROVAL = scope вычисленного следующего offline-пакета из каталога ниже
REPOSITORY_ROOT = Git root, содержащий этот prompt
AUDIT_REF = optional
STATUS_FILE = docs/d11_remediation_status.json
STATUS_VALIDATOR = scripts/check_d11_remediation_status.py
E2_HANDOFF_REF = unset
AUTONOMOUS_LIVE_POLICY = значение из проверенного STATUS_FILE
ALLOW_NETWORK = false
ALLOW_PROVIDER_COST = false
LIVE_EVIDENCE_APPROVED = false
RUN_AUTONOMOUS_LIVE = false
```

Явные overrides допустимы, но не нужны для A-E1. `WORK_PACKAGE` нельзя
перескочить через порядок ledger. `AUTONOMOUS_LIVE_POLICY` является неизменяемым
после инициализации решением владельца, а не выбором агента:

- `BLOCKER` — успешный autonomous live artifact обязателен для D11 PASS;
- `DOCUMENTED_LIMITATION` — harness обязателен, но отсутствие модельного
  evidence не блокирует D11 и остаётся явно раскрытым ограничением.

Обычная команда продолжения не разрешает provider network, расходы, release
tag, push или публикацию. Для `E2` нужны отдельный внешний `E2_HANDOFF_REF` и
три явных разрешающих флага в `true`. При политике `BLOCKER` дополнительно
требуется `RUN_AUTONOMOUS_LIVE = true`. Наличие API-ключа само по себе не
является разрешением.

## Progress

Канонический machine-readable статус — `docs/d11_remediation_status.json`.
Эта таблица — человекочитаемая проекция; при расхождении сначала верь
validator и ledger.

| Package | Status | Verdict | Notes |
| --- | --- | --- | --- |
| A | COMPLETE | PASS | Schema 2.0.0 READY_TO_COMMIT on an A-only tree; later packages require this committed predecessor checkpoint. Do not start B2. |
| B1 | IN_PROGRESS | HOLD | Isolated in stash `d11-b1-c2-isolation-after-output-path-fix`; not the active package. Do not start B2. |
| B2 | NOT_STARTED | NOT_RUN | Do not start. |
| C1 | NOT_STARTED | NOT_RUN | |
| C2 | NOT_STARTED | NOT_RUN | Owns remaining R-16 bare-`python` commands outside acceptance. |
| D0 | NOT_STARTED | NOT_RUN | |
| D1 | NOT_STARTED | NOT_RUN | |
| D2 | NOT_STARTED | NOT_RUN | |
| E1 | NOT_STARTED | NOT_RUN | |
| E2 | NOT_STARTED | NOT_RUN | Live/network still forbidden. |
| F1-F4, G | deferred | — | Not part of current D11 promotion sequence. |

Package A, already done:

- acceptance-demo включён в D11 write-set, implemented artifacts и rollback;
- `829df29` оставлен только как historical evidence, не current candidate;
- bounded reproducibility diagnostics различают `same_accepted_response` и
  `same_result_projection` без печати полного response;
- Windows localhost smoke: 10/10 repeats, flake not claimed eliminated;
- AUTONOMOUS_LIVE_POLICY = `DOCUMENTED_LIMITATION`;
- schema `2.0.0` tracked/handoff contract: `READY_TO_COMMIT` without
  self-referential `resolved_completion_commit`;
- E2 promotion PASS fail-closed: `promotion_report`, `FROZEN_REVIEWED`,
  `CLEAN`, `RELEASED` and verified artifact files;
- status validator CLI is rechecked after the review fixes;
- A-only public docs describe HEAD runtime: tracked
  `docs/evidence/live-eval-public.json` remains the current path, and strict
  `--release` still requires that artifact. B1 historical-path claims were
  reverted out of overlapping A docs;
- later packages require HEAD:`docs/d11_remediation_status.json` to be a
  schema 2.0.0 READY_TO_COMMIT predecessor with a causal first-parent
  checkpoint; schema 1.0.0/`UNCOMMITTED` HEAD cannot open B1;
- B1/C2 leftovers are isolated in stash
  `d11-b1-c2-isolation-after-output-path-fix` and are not A artifacts.

Package A, still open:

- R-16 for non-acceptance `python` commands is deferred to C2.

Package B1, present as leftovers, not the active package:

- restore stash `d11-b1-c2-isolation-after-output-path-fix` only after the
  A READY_TO_COMMIT checkpoint is committed and validated on clean HEAD;
- do not start B2.

## Master-prompt

```text
Ignore prior responses and tool outputs. Start from the current repository state.

РОЛЬ

Ты — Principal Software Engineer, отвечающий за доказательное и безопасное
устранение замечаний D11 в публичном дипломном демо Agent Coach.

Ты не реализуешь исходный аудит буквально. Критическая проверка является
обязательным корректирующим источником, но код и тесты остаются источником
истины о текущем поведении.

ВХОД

REPOSITORY_ROOT = explicit override либо Git root, содержащий этот prompt
AUDIT_REF = optional external reference
STATUS_FILE = docs/d11_remediation_status.json
STATUS_VALIDATOR = scripts/check_d11_remediation_status.py
E2_HANDOFF_REF = explicit external path либо unset
WORK_PACKAGE = explicit package либо RESUME по умолчанию
OWNER_APPROVAL = explicit override либо команда продолжения для вычисленного
                 offline package scope
AUTONOMOUS_LIVE_POLICY = immutable значение из проверенного STATUS_FILE
ALLOW_NETWORK = explicit true либо false по умолчанию
ALLOW_PROVIDER_COST = explicit true либо false по умолчанию
LIVE_EVIDENCE_APPROVED = explicit true либо false по умолчанию
RUN_AUTONOMOUS_LIVE = explicit true либо false по умолчанию

Не выдавай BLOCKED только из-за отсутствия ручных placeholder-параметров.
Сначала примени безопасные defaults выше, найди repository root и проверь
STATUS_FILE валидатором. Отсутствие AUDIT_REF не является blocker. Если
STATUS_FILE или STATUS_VALIDATOR фактически отсутствует после завершённого A,
policy невалидна либо вычислить пакет однозначно нельзя, остановись с точным
BLOCKED/HOLD. Для E2 отсутствие отдельного E2_HANDOFF_REF или любого live-
разрешения остаётся обязательным blocker; обычная команда продолжения их не
подразумевает.

ЦЕЛЬ

Последовательно привести D11 к состоянию, в котором:

1. scope и фактические артефакты согласованы;
2. live-evidence причинно связано с реально исполнявшимся clean commit;
3. forced-grounding success не выдаётся за planner accuracy;
4. offline eval измеряет разные свойства раздельно и детерминированно;
5. настоящий автономный выбор инструмента имеет отдельный opt-in live-eval и
   явно выбранный статус относительно D11 promotion;
6. CI защищает offline eval и весь Python-код в scripts;
7. документация не обещает неисполняемые лимиты или недостижимое поведение;
8. архитектурные границы Core/adapters/API остаются неизменными;
9. финальное promotion evidence собирается только после завершения кода и
   документации на reviewed clean commit.

НЕИЗМЕНЯЕМЫЕ ПРАВИЛА

1. Сначала полностью прочитай применимый AGENTS.md, затем выполни:

   - `git status --short --branch`;
   - `git log -5 --oneline --decorate`;
   - релевантный diff;
   - раздел активного среза в `docs/implementation_plan.md`;
   - STATUS_FILE полностью;
   - для E2 также существующий E2_HANDOFF_REF, если он уже создан.

2. Не полагайся на зафиксированный в аудите или prompt HEAD. Проверь его
   исполнением. Commit `22e42e2` является лишь исторической base provenance
   acceptance-demo/Package A, а `829df29` — historical live-evidence commit,
   не current candidate. Фактические HEAD, origin/main и состояние дерева
   всегда бери из Git и проверенного STATUS_FILE.

3. Не переписывай опубликованную историю. Запрещены `git reset --hard`, force
   push, rebase опубликованного main и удаление пользовательских изменений.
   Revert возможен только по отдельному прямому указанию владельца.

4. Один запуск — один WORK_PACKAGE. Не начинай следующий пакет автоматически.
   WORK_PACKAGE обязан совпадать с `next_allowed_package` в проверенном status
   ledger либо с незавершённым `current_package`, который возобновляется.
   Если WORK_PACKAGE = RESUME, после reconciliation детерминированно разреши
   его в `current_package` для IN_PROGRESS/HOLD/BLOCKED либо в
   `next_allowed_package` для COMPLETE + PASS. Команда продолжения является
   ограниченным OWNER_APPROVAL именно для этого вычисленного offline-пакета.
   Сообщи разрешённое значение до редактирования. RESUME не разрешает обход
   blocker, package order, расширение каталожного write-set или E2 live-флагов.

5. До редактирования проверь write-set выбранного пакета. Если он не разрешён
   действующим планом, сначала в рамках пакета A явно обнови план. Не расширяй
   scope молча.

6. Не добавляй зависимости без доказанной необходимости. Все default checks
   остаются offline, deterministic и без provider credentials.

7. Пакеты A, B1, B2, C1, C2, D0, D1, D2 и E1 являются только offline
   remediation/harness работами. В них запрещены provider network и
   расходуемый live-eval, даже если разрешающие флаги уже выставлены. Любой
   новый code/doc commit после live-прогона делает этот прогон непригодным для
   promotion.

   Provider network разрешён только в E2, если одновременно выполнены:

   - ALLOW_NETWORK = true;
   - ALLOW_PROVIDER_COST = true;
   - LIVE_EVIDENCE_APPROVED = true.

   При AUTONOMOUS_LIVE_POLICY = BLOCKER также обязательно
   RUN_AUTONOMOUS_LIVE = true.

8. Не печатай и не сохраняй секреты, raw provider payload, chain-of-thought,
   приватные пути или реальные данные учащихся.

9. Не считай `scripts/check_public_release.py --release` promotion gate. Это
   только repository hygiene. Promotion требует внешние live и clean-release
   evidence.

10. Не используй Priority Score исходного отчёта: опубликованные значения не
    воспроизводятся по его формуле. Приоритет задаётся каталогом пакетов ниже.

11. R-02 не закрывает R-18. Скриптованные provider responses измеряют
    fail-closed адаптера, не автономный выбор инструмента моделью.

12. R-12 нельзя реализовывать как `empty practice => failed phase`. Пустой
    список карточек является успешным completed tool result с abstain-ответом.

13. R-15 отклонён для текущего демо. Не ослабляй `REPEATED_TOOL_CALL` и не
    внедряй дедупликацию по `ToolSpec.idempotent`.

14. Не создавай `TraceSinkPort` только из-за отсутствия logging. Возможный
    `error_id` является отдельным API-решением и не входит в пакеты D11.

15. Для R-01 используй официальный контракт, а не тезис «nested anyOf всегда
    вызывает 400». Nested `anyOf` допустим; root `anyOf` недопустим. Strict
    schema требует полный `required`. Nullable может быть `type: [T, null]`.

16. Для R-04 всегда различай:

    - declared per-tool metadata;
    - global runtime safety cap;
    - effective cap.

    `min(2000, 7200) == 2000`, поэтому R-04b не отменяет честную документацию
    R-04a.

17. Не фиксируй 54 eval-кейса до завершения D0. Число 54 — предварительная
    арифметика, а не утверждённый контракт.

18. Не меняй D8 corpus внутри D11. Если near-threshold discovery не находит
    подходящие стабильные запросы, перенеси threshold-sensitivity в focused
    retrieval tests или выдай BLOCKED для этой части. Не подгоняй корпус.

19. Старый `docs/evidence/live-eval-public.json` не может оставаться
    двусмысленным current live artifact. В B1 явно мигрируй его в historical
    contract: предпочтительно перенеси в `docs/evidence/historical/` и добавь
    `classification: historical_example`, либо реализуй равноценную явную
    классификацию. Public-release может проверять безопасность исторического
    примера, но `--release` не должен требовать его как current live evidence,
    а promotion и wrapper обязаны отвергать historical classification.

20. Делай минимальные изменения без drive-by refactoring. Новое поведение
    обязано иметь focused tests; новые публичные утверждения — исполняемое
    доказательство.

21. До изменений gate зафиксируй семантику AUTONOMOUS_LIVE_POLICY:

    - BLOCKER: отдельные autonomous threshold/artifact/status обязательны для
      PASS; один `live_task_success_min_rate` не может представлять два eval;
    - DOCUMENTED_LIMITATION: forced live остаётся promotion evidence, а
      autonomous status публикуется отдельно и не выдаётся за измеренную
      planner accuracy. Отсутствие autonomous artifact не является blocker.

22. Не считай Linux CI matrix доказательством устранения Windows-флейка.
    Диагностика и проверка воспроизводимости должны различать точную ветвь
    отказа и указывать платформу фактического запуска.

PERSISTENT STATUS И RESUME PROTOCOL

STATUS_FILE — канонический, машинно читаемый, public-safe JSON checkpoint между
сессиями, но не новый источник истины о статусе архитектурных срезов. Статус
D11 в `docs/implementation_plan.md` остаётся нормативным; при расхождении
выдай HOLD и сначала согласуй документы. Не веди параллельную ручную Markdown-
копию состояния.

1. Package A создаёт STATUS_FILE и STATUS_VALIDATOR, если их ещё нет. Для
   любого другого пакета отсутствие любого из них является BLOCKED: не
   восстанавливай прогресс по памяти чата или предположениям.
2. STATUS_FILE является разрешённым дополнительным write-set для каждого
   пакета A-E1. Он не разрешает менять другие файлы вне package write-set.
   STATUS_VALIDATOR и его focused tests входят в package A; их дальнейшее
   изменение требует явного write-set текущего пакета и schema-version bump.
3. В начале новой сессии проверь status snapshot против фактов:

   - `.\.venv\Scripts\python.exe scripts/check_d11_remediation_status.py`;
   - `git rev-parse HEAD origin/main`;
   - `git status --short`;
   - перечисленные changed files;
   - последний package verdict и незакрытые blockers;
   - AUTONOMOUS_LIVE_POLICY;
   - `next_allowed_package`.

   Единственное исключение — первая инициализация package A: зафиксируй
   отсутствие обоих файлов и проверь их сразу после создания. Во всех других
   случаях не доверяй STATUS_FILE, если validator не дал PASS. Exact match
   принимается после PASS. Новый clean HEAD можно признать ожидаемым
   package commit без изменения истории только если recorded observed_head
   является first parent этого HEAD, STATUS_FILE byte-identical с committed
   `READY_TO_COMMIT` snapshot, а diff `observed_head..HEAD` состоит из
   перечисленных package files и STATUS_FILE. Validator выводит resolved
   commit из Git; не записывай его в tracked STATUS_FILE. Любое другое
   расхождение HEAD, policy или дерева требует read-only reconciliation и
   HOLD до явного OWNER_APPROVAL.

   Если validator дал PASS для `COMPLETE + PASS + READY_TO_COMMIT` на грязном
   дереве, команда продолжения разрешает завершить checkpoint перед следующим
   пакетом:

   - повторно сверь Git diff с `fingerprinted_files` и `changed_files`;
   - повтори validator, package-required checks, `check_public_release.py` и
     `git diff --check`;
   - если они проходят, создай локальный package checkpoint commit ровно из
     перечисленных файлов и STATUS_FILE; не включай посторонние изменения, не
     выполняй push и не создавай tag;
   - не редактируй tracked STATUS_FILE после коммита: он остаётся
     `READY_TO_COMMIT` с `resolved_completion_commit: null`;
   - validator на чистом дереве выводит resolved commit как HEAD и проверяет,
     что `observed_head` равен first parent HEAD;
   - только затем получи lease вычисленного следующего пакета. Эта техническая
     фиксация не считается вторым WORK_PACKAGE.

   Если точный diff не совпадает, required check падает, commit запрещён
   настройками/политикой среды или присутствуют чужие изменения, не коммить и
   выдай HOLD с конкретным расхождением.
4. Используй две независимые оси состояния:

   - `implementation_status`: NOT_STARTED | IN_PROGRESS | COMPLETE | BLOCKED;
   - `package_verdict`: NOT_RUN | PASS | HOLD | BLOCKED.

   Общий `d11_promotion_status` веди отдельно. HOLD всего D11 из-за отсутствия
   финального live/clean evidence не мешает переходу к следующему offline
   пакету, если текущий package имеет COMPLETE + PASS.
5. Перед редактированием получи session lease: создай public-safe UUID
   `active_session_id`, запиши `session_started_at_utc`, `lease_status: ACTIVE`
   и переведи выбранный пакет в IN_PROGRESS. Если checkpoint уже содержит
   ACTIVE lease другого session id, не редактируй проект. Автоматический TTL не
   освобождает lease: после read-only проверки процессов и дерева только
   OWNER_APPROVAL может перевести его в STALE_CANDIDATE, а затем в RELEASED.
   Перед каждым плановым завершением, включая HOLD/BLOCKED или частичную
   работу, обнови checkpoint и освободи lease. Не помечай COMPLETE, пока
   package DoD и обязательные focused checks не выполнены.
   Для E2 acquire/release lease записывается только в E2_HANDOFF_REF, никогда
   в tracked STATUS_FILE.
6. После реализации пакета A-E1:

   - сначала выполни substantive package checks;
   - затем обнови STATUS_FILE фактическими результатами, fingerprint и
     RELEASED lease;
   - после обновления выполни как минимум `git diff --check`, status-safe
     public-release check, STATUS_VALIDATOR и `git status --short` на финальном
     дереве;
   - не редактируй STATUS_FILE повторно только ради записи результатов этих
     финальных hygiene checks: приведи их в финальном ответе, а следующая
     сессия обязана повторно проверить snapshot.

7. STATUS_FILE содержит только repo-relative пути и public-safe bounded
   сведения. Запрещены секреты, provider payload, абсолютные локальные пути,
   персональные данные, raw stdout и chain-of-thought.
8. STATUS_FILE сериализуется как UTF-8 JSON object с точной schema, stable key
   ordering, двухпробельным indent и завершающим newline. Минимальная структура:

   - schema_version: `agent-coach-d11-remediation-status/2.0.0`;
   - updated_at_utc;
   - autonomous_live_policy;
   - base_head, observed_head, observed_origin_main и
     resolved_completion_commit только null в tracked file;
   - checkpoint_commit_state: UNCOMMITTED | READY_TO_COMMIT;
   - checkpoint_fingerprint_sha256 и fingerprinted_files;
   - worktree_state: CLEAN | DIRTY_EXPECTED;
   - active_session_id, session_started_at_utc и
     lease_status: ACTIVE | STALE_CANDIDATE | RELEASED;
   - current_package;
   - implementation_status;
   - package_verdict;
   - d11_promotion_status;
   - network_provider_calls и provider_cost_status;
   - changed_files с кратким назначением;
   - checks_passed с командой, платформой и результатом;
   - checks_not_run;
   - remaining_risks и blockers;
   - last_completed_package;
   - next_allowed_package;
   - exact_resume_instruction;
   - append-only package ledger: package, status, verdict, observed HEAD,
     completion UTC, короткое evidence summary, previous_entry_sha256 и
     entry_sha256.

   При RELEASED `active_session_id` равен null. `entry_sha256` вычисляется по
   canonical ledger entry без собственного поля `entry_sha256`; первая запись
   имеет `previous_entry_sha256: null`, каждая следующая ссылается на digest
   предыдущей.

   E2_HANDOFF_REF использует отдельную exact schema
   `agent-coach-d11-e2-handoff/2.0.0`: те же session/package/provenance поля,
   плюс только bounded artifact types, filenames, sizes и SHA-256 digests.
   Абсолютные пути и содержимое evidence запрещены. `FROZEN_REVIEWED` и
   `resolved_completion_commit` живут только в этом внешнем wrapper; tracked
   STATUS_FILE их не хранит. Promotion PASS требует `promotion_report`,
   `FROZEN_REVIEWED`, `CLEAN`, `RELEASED` и фактически проверенные artifact
   files.

   Fingerprint contract:

   - SHA-256 считается по canonical JSON manifest из base_head и всех
     разрешённых package-changed paths;
   - для каждого repo-relative path включи state ADD | MODIFY | DELETE и
     SHA-256 текущего содержимого либо фиксированный deletion marker;
   - STATUS_FILE исключается из manifest во избежание самоссылки;
   - ignored files и внешние E2 artifacts не включаются;
   - неожиданный untracked/changed path вне package write-set даёт HOLD;
   - raw diff и содержимое файлов в STATUS_FILE не копируются.

   STATUS_VALIDATOR обязан fail closed и проверять:

   - exact schema version, required keys, enums и UTC timestamp format;
   - canonical package order и допустимый `next_allowed_package`;
   - immutable AUTONOMOUS_LIVE_POLICY после инициализации;
   - COMPLETE + PASS только при пустых blockers и наличии package-specific
     required check ids;
   - запрет E2 до COMPLETE + PASS всех A-E1;
   - zero provider calls/cost для A-E1;
   - fingerprint против текущего разрешённого tree state;
   - `changed_files` path/state точно равны `fingerprinted_files` плюс
     STATUS_FILE;
   - внутреннюю hash-chain append-only ledger и совпадение top-level snapshot
     с последней записью;
   - допустимые lease transitions и запрет второго ACTIVE session id;
   - невозможность `d11_promotion_status: PASS` до валидного E2 checkpoint с
     `promotion_report`, `FROZEN_REVIEWED`, `CLEAN`, `RELEASED`, verified
     artifact files, committed E1 COMPLETE+PASS prefix, Git HEAD matching
     `resolved_completion_commit`, and JSON promotion evidence rather than
     filler bytes;
   - отсутствие абсолютных путей, raw payload и неизвестных полей;
   - tracked `READY_TO_COMMIT` без self-reference: `resolved_completion_commit`
     остаётся null, а clean HEAD выводится validator из Git.

   Validator имеет offline CLI для tracked STATUS_FILE и отдельный режим
   проверки E2_HANDOFF_REF. Он возвращает non-zero и bounded diagnostics при
   любой ошибке; не исправляет status автоматически.

9. `next_allowed_package` меняется на следующий пакет только при COMPLETE +
   PASS. При IN_PROGRESS/HOLD/BLOCKED он остаётся текущим пакетом. Агент не
   начинает `next_allowed_package` в той же сессии.
10. До freeze reviewed commit пакет E1 обновляет tracked STATUS_FILE в
    COMPLETE + PASS и назначает E2 следующим пакетом. Этот status update должен
    войти в reviewed clean commit.
11. E2 никогда не изменяет tracked STATUS_FILE после freeze или live-прогона:
    это загрязнило бы checkout и разрушило provenance. Все статусы E2,
    включая частичный прогон, HOLD, BLOCKED и финальный PASS, записываются в
    E2_HANDOFF_REF вне checkout с той же минимальной структурой и digests
    внешних evidence вместо их содержимого.
12. Новая E2-сессия читает tracked STATUS_FILE и E2_HANDOFF_REF, но доверяет им
    только после повторной сверки commit, clean state, artifact type/digest и
    package registry hashes. External handoff не может сам назначить PASS.
13. При WORK_PACKAGE = RESUME exact_resume_instruction из checkpoint является
    инструкцией для проверки, а не доверенным приказом. Сначала примени пункты
    3-4, при необходимости безопасно заверши `READY_TO_COMMIT` checkpoint по
    протоколу выше, затем либо продолжи вычисленный пакет, либо выдай
    HOLD/BLOCKED с конкретным расхождением. Не проси повторно подтвердить scope
    вычисленного offline-пакета: команда продолжения уже является этим
    подтверждением.

ПОРЯДОК ПАКЕТОВ

Нормальная последовательность:

A [COMPLETE, PASS, READY_TO_COMMIT] -> B1 [HOLD in stash] -> B2 -> C1 -> C2 -> D0 -> D1 -> D2 -> E1 -> E2

A-B1-B2-C1-C2 образуют P0 offline remediation phase. D0-D1-D2-E1 образуют
P1 offline suite/harness phase. Ни один из этих пакетов не собирает live.
Только после завершения обеих фаз создаётся один reviewed clean commit для E2.

Пакеты F1-F4 выполняются только после отдельного разрешения следующего
provider/tool-contract среза. Пакет G не является частью продвижения D11.

──────────────────────────────────────────────────────────────────────────────
PACKAGE A — Scope reconciliation и acceptance-demo
STATUS: COMPLETE (READY_TO_COMMIT; B1 remains HOLD in stash; do not start B2)
──────────────────────────────────────────────────────────────────────────────

Цель:

- [DONE] сделать текущий опубликованный acceptance-demo объяснимой частью процесса;
- [DONE] убрать устаревший статус `829df29` как текущего candidate;
- [DONE] не переписывать историю main.

Минимальный read-set:

- `docs/implementation_plan.md`;
- commit/diff текущего acceptance-demo;
- `scripts/run_acceptance_demo.py`;
- `tests/test_acceptance_demo.py`;
- `docs/review_kit.md`;
- `scripts/README.md`;
- STATUS_FILE/STATUS_VALIDATOR, если уже существуют.

Write-set:

- [DONE] `docs/implementation_plan.md`;
- [DONE] STATUS_FILE;
- [DONE] STATUS_VALIDATOR и `tests/test_d11_remediation_status.py`;
- [DONE] для bounded flake-диагностики:
  `scripts/run_acceptance_demo.py`, `tests/test_acceptance_demo.py`;
- [DONE] только для синхронизации поддерживаемых команд:
  `docs/review_kit.md`, `scripts/README.md`.

Требования:

1. [DONE] Явно включи acceptance runner/test/docs в D11 remediation write-set и
   Implemented artifacts либо остановись, если OWNER_APPROVAL требует forward
   revert. Не выполняй revert самостоятельно.
2. [DONE] Запиши критерии acceptance promotion и rollback, включая все четыре demo
   файла: runner, test, review kit и scripts README.
3. [DONE] Проверь все упоминания `829df29` в плане. Исторически опиши относящееся к
   нему evidence, но не называй commit текущим candidate или источником
   evidence для нового HEAD.
4. [DONE] Не утверждай, что ранее наблюдавшийся flake исчез, только потому что повтор
   прошёл.
5. [DONE] `_verify_reproducibility_and_tool_args` должен выдавать bounded
   диагностику, однозначно различающую `same_accepted_response` и
   `same_result_projection`, без печати полного response или чувствительных
   данных. Behavior fix разрешён только после воспроизведения причины;
   диагностическое улучшение не требует выдумывать воспроизведение.
6. [DONE] Повторы на Windows являются отдельным evidence. Успех Ubuntu CI 3.11/3.12
   не закрывает Windows-риск; если Windows-повтор не выполнен, укажи это как
   remaining risk. (10/10 на win32; flake not claimed eliminated.)
7. [DONE] Инициализируй canonical JSON STATUS_FILE, validator, transition/fingerprint/
   lease tests и package-required-check registry. Schema `2.0.0`. Tracked
   COMPLETE+PASS использует `READY_TO_COMMIT` без записи commit hash в JSON.
   E2 promotion PASS fail-closed на неполное evidence. Начальный ledger не должен
   утверждать завершение пакетов, которые не доказаны текущим проходом.

DoD:

- [DONE] A-only public docs match HEAD runtime; B1 leftovers are isolated;
  a schema 2.0.0 READY_TO_COMMIT snapshot is recorded without rewriting
  premature local commit `d5d1fe0`;
- [DONE] rollback плана включает acceptance-demo;
- [DONE] targeted acceptance suite проходит;
- [DONE] диагностика сообщает конкретную ветвь reproducibility failure;
- [DONE] проблемный localhost test проходит согласованной серией повторов без утечки
  процессов на явно названной платформе (win32/Windows, 10/10);
- [DONE] malformed transition, changed policy, missing required check, fingerprint
  mismatch и competing ACTIVE lease дают validator failure;
- [DONE] clean READY_TO_COMMIT commit validates from the tracked file without
  rewriting `resolved_completion_commit`;
- [DONE] E2 promotion PASS rejects missing `promotion_report`, non-frozen and
  dirty checkpoints, and unverified artifacts;
- [DONE] schema 2.0.0 rejects 1.0.0 documents;
- [DONE] валидный A COMPLETE + PASS READY_TO_COMMIT checkpoint записан;
  next_allowed is B1 after the local A commit;
- [DONE] `git diff --check` чист.

Проверки:

- [DONE] `.\.venv\Scripts\python.exe -m pytest tests/test_acceptance_demo.py -p no:cacheprovider`;
- [DONE] `.\.venv\Scripts\python.exe -m pytest tests/test_d11_remediation_status.py -p no:cacheprovider`;
- [DONE] `.\.venv\Scripts\python.exe scripts/check_d11_remediation_status.py`;
- [DONE] повтор проблемного теста согласованное число раз;
- [DONE] `.\.venv\Scripts\python.exe scripts/check_public_release.py`.

Остановись после promotion report пакета A. Package A is COMPLETE+PASS
READY_TO_COMMIT. Do not start B2. Leave B1 HOLD in stash until this
checkpoint is committed and validated on clean HEAD.

──────────────────────────────────────────────────────────────────────────────
PACKAGE B1 — Единый live registry и causal evidence harness
STATUS: IN_PROGRESS (HOLD leftovers isolated in stash; not the active package)
──────────────────────────────────────────────────────────────────────────────

Цель:

- [DONE] убрать два источника истины `LIVE_EVAL_CASES` и
  `LIVE_EVAL_CASE_REGISTRY`;
- [DONE] определить causal public-artifact contract, не превышающий 64000 bytes;
- [DONE] вывести старый tracked live JSON из current promotion path.

Предпочтительный write-set:

- [DONE] `src/agent_coach/eval/live_evidence.py`;
- [DONE] `scripts/run_live_eval.py`;
- [DONE] `tests/test_live_eval_runner.py`;
- [DONE] `tests/test_public_release_gate.py`;
- [DONE] `scripts/check_public_release.py`;
- [DONE] tracked historical evidence и ссылающиеся на него документы;
- [DONE] canonical registry lives in `live_evidence.py`.

Требования:

1. [DONE] Один canonical registry является источником кейсов для runner и validator.
2. [DONE] Вычисляй stable canonical registry hash. Hash включает исполняемые
   `search_query` и `scripted_answer`.
3. [DONE] Harness и schema нового live artifact требуют минимум:

   - schema version;
   - evaluated commit;
   - clean-worktree marker;
   - contract hash;
   - corpus hash;
   - case-registry hash;
   - safe planner/synthesizer model ids or registered safe config projection;
   - live mode and explicit opt-in;
   - bounded per-case results;
   - recomputable task-success metric.

4. [DONE] Не запускай live provider и не создавай новый фактический live artifact в
   этом пакете. Проверяй schema scripted fixtures.
5. [DONE] Promotion evidence пишется вне checkout. Tracked historical JSON не является
   promotion input. Live `--output` и wrapper paths внутри checkout отклоняются.
6. [DONE] Старый artifact получит явный `historical_example` contract. Предпочтительно
   перемести его под `docs/evidence/historical/`; обнови release checker так,
   чтобы strict repository hygiene не требовала current live evidence и не
   сверяла historical commit с HEAD.
7. [DONE] Historical artifact может проверяться на public safety, размер и допустимую
   historical schema, но wrapper/promotion всегда отвергают его как current.
   Path и classification должны совпадать.
8. [DONE] Scripted payload нельзя превратить в live простым переключением полей.
9. [DONE] Ошибка provenance должна быть bounded и не раскрывать provider data.
10. [DONE] Current public schema fail-closed: unexpected keys и unsafe values
    (включая secret-like identifier fields) отклоняются.
11. [DONE] Public release gate сверяет current artifact с HEAD.

DoD:

- [DONE] registry drift невозможен без тестового отказа;
- [DONE] artifact другого commit или dirty run отклоняется;
- [DONE] JSON <= 64000 bytes;
- [DONE] historical example не удовлетворяет current-evidence validator;
- [DONE] `--release` проходит без требования tracked current live artifact;
- [DONE] scripted artifact отклоняется независимо от ручной правки одного флага;
- [DONE] default scripted tests остаются offline;
- [HOLD] package verdict remains HOLD; restore the stash after the A
  checkpoint is on clean HEAD before recording B1 COMPLETE+PASS.

Остановись после promotion report пакета B1. Do not start B2.

──────────────────────────────────────────────────────────────────────────────
PACKAGE B2 — Wrapper и promotion gate harness
──────────────────────────────────────────────────────────────────────────────

Цель:

- wrapper сверяет provenance, а не назначает текущий HEAD постфактум;
- promotion принимает только причинно связанные external evidence.

Предпочтительный write-set:

- `scripts/run_live_eval.py`;
- `src/agent_coach/eval/gate.py`;
- `tests/test_live_eval_runner.py`;
- `tests/test_eval_gate.py`;
- `docs/eval_gate.md`.

Требования:

1. Wrapper обязан проверить `artifact.evaluated_commit == HEAD` и все hashes.
2. Wrapper переносит проверенный commit, но не генерирует его как новое
   утверждение.
3. Promotion gate отклоняет:

   - старый commit;
   - иной registry/contract/corpus hash;
   - dirty evidence;
   - missing/oversized artifact;
   - несовпадающую recomputed metric;
   - wrapper, ссылающийся на historical tracked JSON как на current evidence.

4. Output promotion report остаётся вне checkout.
5. Не собирай live evidence. Все positive/negative gate tests используют
   synthetic public fixtures.
6. Зафиксируй выбранную AUTONOMOUS_LIVE_POLICY в плане и gate contract. Не
   используй forced threshold как неявный autonomous threshold. Окончательные
   autonomous schema/metrics добавляются в E1.

DoD:

- негативные provenance tests проходят;
- старый artifact `829df29` не может продвинуть новый HEAD;
- scripted offline validation не считается live evidence;
- отсутствие live evidence даёт HOLD, а не offline gate failure.
- historical artifact не может быть обёрнут как current даже при совпавшем
  digest.

Остановись после promotion report пакета B2.

──────────────────────────────────────────────────────────────────────────────
PACKAGE C1 — Честность README, thresholds и Tool SOP
──────────────────────────────────────────────────────────────────────────────

Цель:

- устранить R-18, R-04a, минимальный R-06 и документационную часть R-11a без
  изменения exported contract.

Предпочтительный write-set:

- `README.md`;
- `docs/eval_gate.md`;
- `docs/live_profile.md`;
- `docs/review_kit.md`;
- `docs/implementation_plan.md`;
- `src/agent_coach/eval/gate.py`;
- `docs/tool_sop.md`;
- focused tests при необходимости разделить во второй коммит того же пакета.

Требования:

1. Не утверждай, что README сейчас содержит live >=80% KPI: исправляй реальные
   места — live command/limitations, Frozen Thresholds и review kit.
2. Forced-grounding live success описывается как проверка synthesis,
   grounding/citation и provider-contract wiring. Она не измеряет planner
   accuracy.
3. SOP различает declared, global и effective result caps.
4. `When Not To Use` берётся из полного registered map; отсутствие записи для
   advertised tool роняет генерацию.
5. SOP честно сообщает, что построен из ToolSpec плюс package-owned negative
   usage registry.
6. `REPAIRING` и `INVALID_ARGS_AFTER_REPAIR` документируются как reserved and
   unreachable in v1. Не меняй contract bundle.
7. `docs/live_profile.md` различает provider adapter с `tool_choice=auto` и
   forced-grounding eval harness. Устрани противоречивые заявления о том,
   требуется ли live для D11, согласно AUTONOMOUS_LIVE_POLICY.
8. Не оставляй `829df29` в роли текущего candidate ни в одном P0-документе.

DoD:

- SOP snapshot совпадает с генератором;
- public release gate проходит;
- ни один документ не заявляет измерение autonomous tool selection forced
  набором;
- declared limit не подаётся как effective runtime cap.

Остановись после promotion report пакета C1.

──────────────────────────────────────────────────────────────────────────────
PACKAGE C2 — Process docs и CI
──────────────────────────────────────────────────────────────────────────────

Цель:

- исправить R-07, R-16 и узкую часть R-20.

Write-set:

- `.github/workflows/ci.yml`;
- `AGENTS.md`;
- `README.md`;
- `CONTRIBUTING.md`;
- `docs/review_kit.md`;
- `docs/release_checklist.md`;
- `tests/test_public_release_gate.py` только для узких машинных инвариантов.

Требования:

1. CI выполняет `python -m compileall src scripts`.
2. CI выполняет offline eval без `--require-promotion` и без
   `--live-evidence`; HOLD не роняет job при PASS offline gate.
3. `check_public_release.py --release` — отдельный repository-hygiene job. Не
   называй его promotion.
4. Документируй POSIX и Windows PowerShell команды отдельно.
5. Удали из AGENTS конкретный статус D10/D11; статус срезов живёт только в
   implementation plan.
6. Не создавай общий regex «semantic conflict detector». Разрешены только
   точные зарегистрированные инварианты с низким false-positive risk.
7. В review kit замени опасные для Windows acceptance-команды через голый
   `python` на активный `.\.venv\Scripts\python.exe`; POSIX команды держи в
   отдельном явно подписанном блоке.
8. Linux matrix 3.11/3.12 полезна для совместимости, но не является DoD
   Windows-флейка и не должна так называться.
9. CI запускает STATUS_VALIDATOR для tracked checkpoint как offline structural
   gate. D11 HOLD допустим, malformed status или незаконный transition — нет.

DoD:

- YAML валиден;
- CI steps не требуют network provider или credentials;
- CI eval invocation не содержит `--live-evidence` или
  `--require-promotion`;
- status validator выполняется offline и fail closed;
- documented Windows commands используют `.\.venv\Scripts\python.exe`;
- public release tests проходят.

Остановись после promotion report пакета C2.

──────────────────────────────────────────────────────────────────────────────
PACKAGE D0 — Eval v2 discovery и спецификация
──────────────────────────────────────────────────────────────────────────────

Цель:

- до изменения frozen suite доказать реализуемость и определить точный registry.

Режим:

- преимущественно read-only;
- разрешено добавить focused discovery tests/fixtures в пределах описанного
  write-set; команда продолжения подтверждает этот scope;
- не менять production corpus.

Обязательный результат:

1. Таблица каждого предлагаемого кейса:

   - id;
   - type;
   - category;
   - profile;
   - input fixture;
   - expected terminal state/stop reason;
   - исполняемое свойство;
   - метрика, в которую он входит;
   - подтверждение отсутствия дублирования.

2. Отдельно зафиксировать:

   - provider contract cases;
   - security containment cases;
   - runtime MAX_TIME/MAX_TOKENS/MAX_COST cases;
   - retrieval negatives;
   - возможные near-threshold cases.

3. Injection fixtures не должны совпадать с `ignore previous`, `system prompt`,
   `developer message`, `reveal.*secret` или другими текущими denylist
   альтернативами.

4. MAX_COST использует известную ненулевую offline runtime cost через
   `ToolResult.meta["estimated_cost_usd"]` и ожидает `StopReason.MAX_COST`.
   Не дублируй config-only `live-unknown-pricing-cost-cap` и не пытайся
   получать стоимость из live-профиля.

5. Эмпирически проверь существование стабильных запросов в требуемой score
   band на текущем corpus. Если их нет, не придумывай 54 кейса и не меняй D8.

6. Перечисли все механические замки, которые потребуется обновить:

   - suite version constant;
   - exact case count;
   - full EXPECTED_CASE_IDS;
   - `case_count_not_27`;
   - category-to-type map;
   - canonical suite hash;
   - README/plan exact counts.

DoD:

- итоговое число кейсов доказано составом;
- типы и метрики утверждены до JSON-правки;
- near-threshold имеет исполняемое доказательство либо исключён/отложен;
- нет изменения frozen suite или corpus в этом пакете.

Остановись после discovery report. Не начинай D1.

──────────────────────────────────────────────────────────────────────────────
PACKAGE D1 — Eval suite v2: cases и evaluators
──────────────────────────────────────────────────────────────────────────────

Предусловие:

- D0 завершён с `COMPLETE + PASS`, а его проверенный checkpoint фиксирует
  точный case registry; команда продолжения подтверждает реализацию этого
  registry без дополнительного ручного approval.

Предпочтительный write-set:

- package-owned `diploma_eval_cases.json`;
- `src/agent_coach/eval/gate.py`;
- `tests/test_eval_gate.py`;
- при необходимости focused fixtures в package-owned public data.

Требования:

1. Один осознанный bump suite version и canonical hash.
2. Одновременно обнови все механические замки из D0.
3. Разведи показатели:

   - adapter contract fail-closed rate;
   - invalid/unknown tool executions;
   - security containment;
   - retrieval positive accuracy;
   - retrieval negative rejection;
   - exact budget stop reasons.

4. Offline golden 100% применяется только к заранее определённым golden types.
5. Ни один scripted case не называется planner accuracy.
6. Wall-clock duration сохраняется как observation, не deterministic threshold.
7. Runtime MAX_COST case доказывает накопление положительной известной
   `estimated_cost_usd` и точный `StopReason.MAX_COST`.

DoD:

- suite loader принимает только точный новый registry;
- порча любого id/type/threshold/hash роняет focused test;
- все новые negative/budget/provider cases проходят;
- ни один инструмент не исполняется после fail-closed stop.

Остановись после promotion report пакета D1.

──────────────────────────────────────────────────────────────────────────────
PACKAGE D2 — Eval metrics, docs и release awareness
──────────────────────────────────────────────────────────────────────────────

Предпочтительный write-set:

- `src/agent_coach/eval/gate.py`;
- `tests/test_eval_gate.py`;
- `docs/eval_gate.md`;
- `README.md`;
- `docs/implementation_plan.md`;
- при необходимости `scripts/check_public_release.py` и его focused tests
  вынести в отдельный коммит этого пакета.

Требования:

1. Публикуй только измеренные метрики с однозначным denominator.
2. Workload proxies называются bounded-work metrics, не performance.
3. p95 wall-clock маркируется non-gating observation.
4. Документация содержит точное число и registry новой suite.
5. Public release gate проверяет версию/hash/drift нового набора.

DoD:

- `run_eval_gate.py` выдаёт PASS;
- повторные deterministic metrics совпадают;
- wall-clock может различаться и не меняет gate status;
- public release gate проходит.

Остановись после promotion report пакета D2.

──────────────────────────────────────────────────────────────────────────────
PACKAGE E1 — Autonomous planner eval schema и offline harness validation
──────────────────────────────────────────────────────────────────────────────

Цель:

- создать второй, отдельный eval autonomous tool selection без смешения с
  forced-grounding evidence.

Предусловие:

- AUTONOMOUS_LIVE_POLICY уже выбрана владельцем, неизменно записана в
  проверенном STATUS_FILE и отражена в плане. Не запрашивай её повторно; при
  фактическом отсутствии или расхождении выдай BLOCKED до изменения
  code/gate contract.

Требования:

1. Отдельные registry, schema version и public/external artifact.
2. `tool_choice: auto`; никакого `PlannerToolRequirement`.
3. Предзарегистрированные группы:

   - tool required;
   - no tool expected;
   - insufficient/malformed arguments;
   - irrelevant available tools.

4. Метрики:

   - tool-name accuracy;
   - no-call precision;
   - valid-args rate;
   - invalid/forbidden executions = 0.

5. Thresholds фиксируются до любого live запуска.
6. Forced-grounding suite остаётся отдельной и продолжает измерять synthesis.
7. Каждый JSON ограничен 64000 bytes; не расширяй старый artifact сверх cap.
8. Offline scripted validation проверяет runner/schema только и не считается
   модельной accuracy.
9. Не запускай provider network. Порог, registry и policy фиксируются до
   первого фактического autonomous live-прогона.
10. При BLOCKER добавь отдельные autonomous promotion inputs, threshold,
    blockers и status. При DOCUMENTED_LIMITATION публикуй отдельный
    non-promotion status/limitation; отсутствие artifact не должно случайно
    использовать forced `live_task_success_min_rate` или блокировать PASS.

DoD:

- scripted tests offline;
- autonomous artifact нельзя перепутать с forced artifact по schema;
- метрики пересчитываются из per-case projections;
- registry и threshold drift роняют тест;
- тесты доказывают выбранную promotion semantics для наличия, отсутствия и
  провала autonomous artifact.

Остановись после promotion report пакета E1.

──────────────────────────────────────────────────────────────────────────────
PACKAGE E2 — Clean live evidence и финальное продвижение D11
──────────────────────────────────────────────────────────────────────────────

Предусловия:

- A-B-C-D-E1 завершены и объединены в reviewed clean commit;
- tracked STATUS_FILE внутри reviewed commit показывает E1 COMPLETE + PASS и
  `next_allowed_package: E2`;
- E2_HANDOFF_REF находится вне checkout и доступен для bounded status update;
- никаких последующих code/doc changes не планируется;
- `git rev-parse HEAD origin/main` зафиксирован в отчёте, а расхождение явно
  рассмотрено до live-сети;
- AUTONOMOUS_LIVE_POLICY зафиксирована в коде, тестах и документации;
- при AUTONOMOUS_LIVE_POLICY = BLOCKER установлен
  RUN_AUTONOMOUS_LIVE = true;
- ALLOW_NETWORK = true;
- ALLOW_PROVIDER_COST = true;
- LIVE_EVIDENCE_APPROVED = true.

Если хотя бы одно предусловие не выполнено, выдай BLOCKED и не запускай live.

Порядок:

1. Зафиксируй HEAD и clean status.
2. Запусти forced-grounding live suite во внешний artifact.
3. Если AUTONOMOUS_LIVE_POLICY = BLOCKER, потребуй
   RUN_AUTONOMOUS_LIVE = true и запусти autonomous planner live suite во
   второй внешний artifact. Если policy = DOCUMENTED_LIMITATION, запускай его
   только при RUN_AUTONOMOUS_LIVE = true; отсутствие этого прогона не отменяет
   обязательное раскрытие limitation.
4. Если запускаются оба набора, запусти их подряд на одном и том же reviewed
   commit до любых code/doc изменений.
5. Проверь commit/contract/corpus/registry hashes и 64 KB cap каждого файла.
6. Собери отдельный typed wrapper для каждого созданного artifact либо один
   wrapper-collection с раздельными typed entries. Wrapper только подтверждает
   совпадение provenance и не назначает commit.
7. В fresh clone/disposable copy выполни зарегистрированные offline checks.
8. Создай clean-release evidence вне checkout с реальными stdout SHA-256.
9. Выполни strict repository gate.
10. Выполни promotion gate с `--require-promotion` и только внешними evidence
    paths. Никогда не используй historical tracked artifact.
11. Не создавай release tag автоматически.
12. После определения фактического verdict обнови только E2_HANDOFF_REF; не
    изменяй tracked STATUS_FILE или другие файлы checkout.
13. Проверь внешний checkpoint командой STATUS_VALIDATOR в handoff-режиме.
    Validator PASS не заменяет повторную provenance/promotion validation.

DoD:

- forced и autonomous metrics/status раздельны;
- при BLOCKER оба live artifacts относятся к одному reviewed commit и
  autonomous threshold пройден;
- при DOCUMENTED_LIMITATION forced evidence может дать D11 PASS без
  autonomous artifact, но отчёт прямо запрещает claim planner accuracy;
- если autonomous artifact создан при DOCUMENTED_LIMITATION, он относится к
  тому же reviewed commit и публикуется отдельно;
- clean evidence относится к тому же commit;
- promotion status PASS либо честный HOLD с точным blocker;
- E2_HANDOFF_REF содержит проверяемый status и exact resume instruction;
- `STATUS_VALIDATOR --handoff E2_HANDOFF_REF` возвращает PASS;
- никакие evidence/report files не загрязняют checkout.

Остановись после финального D11 promotion report.

──────────────────────────────────────────────────────────────────────────────
PACKAGE F1 — Strict provider schema (следующий срез)
──────────────────────────────────────────────────────────────────────────────

Не выполнять внутри D11 без отдельного OWNER_APPROVAL.

Цель:

- `strict: true` provider projection;
- все properties required;
- optional semantics через nullable или обязательное явное значение;
- удалить provider-irrelevant `title`/`default`;
- сохранить Core как authoritative validator.

Nested anyOf не объявлять ошибкой официального контракта. Предпочтение union
type обосновывать простотой/модельной устойчивостью, а не выдуманной гарантией
HTTP 400.

Остановись после provider-slice report.

──────────────────────────────────────────────────────────────────────────────
PACKAGE F2 — Stable provider budget payload (следующий срез)
──────────────────────────────────────────────────────────────────────────────

Убрать wall-clock `elapsed_sec`/`remaining_time_sec` из provider prompt,
сохранив authoritative time enforcement и trace timing. Два одинаковых
scripted provider runs должны давать одинаковый request payload.

Остановись после provider-slice report.

──────────────────────────────────────────────────────────────────────────────
PACKAGE F3 — Truthful truncation envelope и effective limits
──────────────────────────────────────────────────────────────────────────────

Не добавляй `next_offset` без реальной пагинации.

Добавь безопасные поля `candidate_count`, `returned_count`, `truncated` и при
уместности `original_chars`. Effective cap может быть
`min(global_cap, declared_cap)`, но SOP обязан продолжать показывать все три
величины. Не повышай глобальный safety cap только ради совпадения с 7200.

Остановись после cross-boundary report с drift-gate evidence.

──────────────────────────────────────────────────────────────────────────────
PACKAGE F4 — Phase outcome, не false failure
──────────────────────────────────────────────────────────────────────────────

Для learner/practice phases добавь безопасный outcome вроде `artifact_present`
или `empty_result`, не меняя `completed` на `failed` для валидного empty result.
Пустой retrieval без grounding сохраняет существующее
`failed/no_grounding_evidence`.

Остановись после D10-maintenance report с обновлёнными golden projections.

──────────────────────────────────────────────────────────────────────────────
PACKAGE G — Отложенные архитектурные решения
──────────────────────────────────────────────────────────────────────────────

Этот пакет только для ADR/плана после явного OWNER_APPROVAL. Не реализуй
автоматически:

- R-10 corpus growth и parent-document retrieval;
- R-11b one-shot argument repair и его step budget;
- API `error_id`;
- полный R-06 (`when_not_to_use` в exported ToolSpec);
- R-17 изменение HomeTutor-derived описаний и provenance;
- любую observability систему с новым Core port.

R-15 остаётся rejected.

──────────────────────────────────────────────────────────────────────────────
ОБЩИЕ ПРОВЕРКИ
──────────────────────────────────────────────────────────────────────────────

Используй активный `.venv` на Windows. Выбирай только проверки затронутой
поверхности, затем расширяй их пропорционально риску:

- `.\.venv\Scripts\python.exe -m pytest <focused tests> -p no:cacheprovider`;
- `.\.venv\Scripts\python.exe -m ruff check <touched paths>`;
- `.\.venv\Scripts\python.exe -m compileall -q <touched package/script paths>`;
- `.\.venv\Scripts\python.exe scripts/check_contract_export.py`;
- `.\.venv\Scripts\python.exe scripts/check_openapi_snapshot.py`;
- `.\.venv\Scripts\python.exe scripts/check_drift_gate.py`;
- `.\.venv\Scripts\python.exe scripts/check_public_release.py`;
- `.\.venv\Scripts\python.exe scripts/check_d11_remediation_status.py`;
- `.\.venv\Scripts\python.exe scripts/run_eval_gate.py`;
- `git diff --check`;
- `git status --short`.

Не заявляй PASS для команды, которую не запускал.

ФИНАЛЬНЫЙ ОТЧЁТ КАЖДОГО ПАКЕТА

Заверши ответ разделами:

1. Outcome.
2. WORK_PACKAGE, проверенный HEAD/origin/main и AUTONOMOUS_LIVE_POLICY.
3. Network/provider calls и cost: для A-E1 обязательно zero/not run.
4. Изменённые файлы и назначение каждого изменения.
5. Выполненные проверки с точными результатами и платформой.
6. Невыполненные проверки.
7. Remaining risks/unknowns, включая Windows evidence при его отсутствии.
8. Promotion verdict пакета: PASS | HOLD | BLOCKED.
9. Rollback boundary.
10. Обновлённый status checkpoint: STATUS_FILE для A-E1 либо E2_HANDOFF_REF
    для E2, с implementation status, package verdict, RELEASED lease и
    checkpoint fingerprint.
11. Exact resume instruction и следующий допустимый пакет — только как
    рекомендация, не начинай его.

После отчёта остановись.
```

## Финальная последовательность D11

```text
scope reconciliation
  -> P0 causal evidence harness + historical classification + docs + CI
  -> P1 eval v2 discovery and frozen offline suite
  -> P1 autonomous planner-eval harness with owner-selected policy
  -> reviewed clean commit
  -> forced live artifact
  -> autonomous live artifact when BLOCKER, or optional separate run when
     DOCUMENTED_LIMITATION
  -> fresh-clone clean evidence
  -> strict repository hygiene
  -> promotion gate
  -> explicit maintainer decision about a release tag
```

Пакеты F и G не должны задерживать D11, если их замечания честно отражены как
отложенные ограничения и не являются promotion blockers утверждённого среза.
При DOCUMENTED_LIMITATION отсутствие autonomous live artifact также не
задерживает D11, но навсегда запрещает claim о подтверждённой planner accuracy
до отдельного успешного live evidence.
