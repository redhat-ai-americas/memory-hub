# Этап 2.3. Независимый аудит разделения Backend User/Admin

Дата: 2026-11-18. Источник требований: `MemoryHub-User-Admin-audit-2026-11-17.md`, раздел E (исходная матрица), с учётом разделов A–G. **Вердикт: AUDIT FAILED**: публичный Route сервиса Auth предоставляет технические `/admin/*` вне human BFF; этот путь защищён общим ключом, но не ограничен сетью и при наличии ключа обходит все объектные и ролевые проверки BFF. Обнаружены также ограниченная утечка агрегата чужих данных и функциональные расхождения. Это статический аудит с unit-тестами; production окружение не проверено.

## A. Git и рабочие копии

- Проверяемая рабочая копия: `/Users/kromashk/ui for memoryhub/memory-hub-backend-admin-user-roles`, ветка `backend-admin-user-roles`, HEAD `c34a15c3a83378fffccd647fe6884681b60ff37a`. Общая база с `main`: `cf37c998eaa6d6b6eea442d89f70361e25da7059`.
- Начальный dirty state: девять modified tracked файлов (`human_adapters.py`, BFF `main.py`, `routes.py`, три BFF теста, Core `graph.py`, `memory.py`, `test_graph_service.py`) и шесть untracked файлов Этапа 2.2 (`role-separation-stage-2.2-2026-11-18.md`, `export_adapter.py`, `graph_adapters.py`, `memory_context.py`, `search_adapter.py`, `test_stage22_adapters.py`). Все они сохранены. Единственное изменение данного аудита — настоящий документ.
- Другие рабочие копии: `memory-hub` (`ui-user-role`, тот же HEAD, dirty Frontend), `memory-hub-extraction-bff` (`codex/extraction-bff`), `memory-hub-ui-admin-user-roles` (`ui-admin-user-roles`). Они не объединялись и не изменялись. UI-контракт прочитан из Git ref `memoryhub-ui`; его файлы не переносились.
- Diff `main...HEAD` затрагивает Auth, MCP, Core, BFF, deployment и тесты; незакоммиченный diff Этапа 2.2 дополнительно затрагивает Core/BFF. Audit не ограничен только HEAD. `git diff --check` не сообщил ошибок. Commit/push/reset/clean не выполнялись. Код, тесты, конфигурация и Frontend не изменены.

## B. Методика и границы доказательств

Для каждого ряда E сопоставлены исходный ID, фактический контракт UI ref `memoryhub-ui`, BFF route, зависимость `get_principal/get_access`, Core/MCP/Auth вызовы, SQL-фильтры и тесты. Пути в доказательствах ниже относятся к проверяемой рабочей копии, если явно не указан `memoryhub-ui:`. Изолированные unit-тесты с `dependency_overrides`, `AsyncMock` и `MagicMock` подтверждают ветвления Python, но не исполнение SQL, транзакционность PostgreSQL, работу OpenShift proxy или доступность интеграций. Наличие MCP scope не засчитывается как human-разрешение.

Для краткости: `R` = `memoryhub-ui/backend/src/routes.py`, `H` = `memoryhub-ui/backend/src/human_adapters.py`, `A` = `memoryhub-ui/backend/src/authorization.py`, `C` = `memoryhub-ui/backend/src/memory_context.py`, `G` = `memoryhub-ui/backend/src/graph_adapters.py`, `S` = `memoryhub-ui/backend/src/search_adapter.py`, `X` = `memoryhub-ui/backend/src/export_adapter.py`, `MA` = `memoryhub-auth/src/routes/admin.py`, `MC` = `memory-hub-mcp/src/core`, `CS` = `src/memoryhub_core/services`. Номера строк относятся к текущему dirty tree, поэтому после изменений могут сдвинуться.

Отчёт Этапа 2.2 изучен как заявление об ожидаемом результате, а не доказательство. Отдельные готовые файлы отчётов Этапов 1, 2 и 2.1 в целевой копии не обнаружены; их изменения проверялись по diff и тестам. Живые данные и сетевые правила кластера недоступны.

## C. Human roles, session и граница доверия

`A:48–68` берёт `x-forwarded-user` ровно один раз, отбрасывает пустое/некорректное значение, проверяет loopback peer и allowlists; роль выводится из `ui_admin_users`, tenant — из серверной `ui_tenant_id`. `A:72–211` содержит разные ветви User/Admin для read, content, write, delete, review и moderation. Admin не наследует User автоматически: собственная personal memory Admin в обычных read проекциях возвращается без текста, а write допускается только в project с direct human admin grant либо в явно настроенном organizational scope. `A:238–272` отдельно считает привязанные агентские identities и прямые human membership; права human project admin не берутся из membership агента. OAuth `identity_type=user|service` и MCP `scopes` используются отдельно (`MC/authz.py:53–120,173–233`), human роль из них не выводится.

Bootstrap: `R:170–251` реализует `/api/me`, `/api/auth/status`, `/api/nav-counts`, `/api/nav-features`; `/api/auth/logout` возвращает переход к `/oauth/sign_out`, но сам cookie не аннулирует. Отсутствующие, duplicate, malformed и неизвестные username покрыты `test_stage2_security.py:55–137`; реальная подпись/длительность cookie зависит от OAuth proxy и не проверена. `memoryhub-ui/Containerfile:42–47` слушает только `127.0.0.1:8080` без proxy headers; `memoryhub-ui/openshift.yaml:76–95,119–145` выставляет только proxy `8443`, включает `--pass-user-headers=true`. Это сужает прямой сетевой доступ, но не доказывает, что произвольный локальный caller или пользователь с разрешённым port-forward не сможет послать единственный поддельный `x-forwarded-user`; сервер сам не проверяет подписанное утверждение proxy. Реальная способность внешнего клиента подменить заголовок **не подтверждена** и не заявлена как установленный эксплойт.

Важная граница интеграции: `memoryhub-ui/Containerfile:10,16,36–37` собирает Frontend из *этой же* ветки. В целевой ветке `memoryhub-ui/frontend/src/api/client.ts` содержит старые вызовы `/graph`, `/graph/search`, `/stats` и не вызывает новые Stage 2.2 routes. Ref `memoryhub-ui` содержит `/memories/browse`, `/memory/{id}/context`, `/graph/all`, `/graph/neighbourhood`, `POST /search`, `/memories/export`, но не собран в данном checkout. Поэтому наличие адаптеров не означает готовую совместную поставку UI/Backend.

## D. Проверка групп операций

### Projects, memory, relationships, entities

- Projects: `H:237–365` реализует list/detail/create/add/remove/self-leave. Tenant берётся из principal, human membership проверяется по username (`H:183–191`), Admin add/remove требует project admin, User может удалить только себя, Core `CS/project.py:283–331` защищает последнего admin. Для открытого проекта User видит публичную строку и агрегаты проекта; invite-only detail требует membership. Сопоставление с реальным PostgreSQL не выполнено.
- Memory write/version/branch: `H:433–503` принимает owner/actor/tenant только после серверной проверки, `H:379–431` проверяет существующий объект и связанные эффекты перед version; Core `CS/memory.py:66,474` выполняет бизнес-операцию. User допускается к own/project, Admin к прямому project admin/явному organizational write. `H:506–541` проверяет обе вершины relationship и reported memory; scope пары должен совпадать. `R:663–719` и `H:544–679` проверяют delete closure и batch до единого SQL update/commit; мок-тесты есть, DB транзакция не проверена.
- Context/graph: `C:51–180` повторно авторизует seed, каждую версию/ветвь/соседа/similar/parent до сериализации. `G:27–113,121–140,152–290` фильтрует node set по tenant/human policy и включает edge лишь при двух выбранных вершинах. `total`, `left_out`, degree и `cut_count` вычисляются для видимого подграфа. Семантический graph mode фактически использует `ILIKE`, не embedding. SQL для connected ranking и глубины в PostgreSQL не проверен.
- Search: `S:74–179` передаёт tenant и human scopes в Core `CS/memory.py:853–1037,1140–1230`, затем повторно проверяет каждый hit перед snippets/explain. User agent IDs применяются лишь к personal ownership; Admin personal content не ищет. Но `rerank` не участвует в вызове, `retrieval` всегда `vector`, а `candidates/omitted_count/weight_filtered` описывают только отданные строки и не являются реальной диагностикой Core. Фильтры branches и `full_only` применяются после ограниченного recall (`S:92,123–153`), поэтому неполная страница возможна при наличии подходящих записей. Никакой запретной информации через `explain` по коду не найден.
- Browse/export: `H:728–974` ограничивает User SQL-предикатом, Admin получает tenant metadata и редактированный текст personal. Counts/facets основываются на той же базе; domain facet исключает скрытый content. `semantic` browse фактически текстовый поиск (`H:817–832`), `near_duplicate=None` (`H:910,970`). `X:34–122` строит User JSONL с повторной проверкой каждой строки и Admin CSV только с metadata, экранирует spreadsheet формулы. Поток читает offset-страницы без стабильного снимка, так что точность экспорта при конкурентных изменениях не доказана.
- Entities: `H:1051–1245` доступен только User; list проверяет видимые MENTIONS, rename/merge до Core повторно проверяют каждый затрагиваемый source и owner entity. Однако detail возвращает `hidden_mentions`, рассчитанный из *всех* same-tenant source, включая недоступные (`H:986–1004,1142–1180`). Тест `test_human_adapters.py:457–471` явно закрепляет `hidden_mentions==1` при чужой memory. Это ограниченная утечка существования/числа чужих упоминаний.

### Moderation, rules, OAuth/MCP

- Moderation: `A:166–198`, `H:544–589` требуют явного category и object/project grant, User quarantine/restore не допускается; Core `CS/admin.py:212–308` выполняет переходы. B23 (`R:1455–1511`) проверяет Admin, report/memory tenant, project admin и запрет self-decision, но только переключает `resolved` без решения review; очередь `/api/review` отсутствует. `CS/memory.py:2153–2208` содержит отдельные technical resolution actions, не соединённые с человеческим BFF. Hard delete `CS/admin.py:311+` существует только как technical вызов, второго Admin approval нет.
- Rules: `R:1003–1201,1276–1311` ограничивает User собственным user-layer, Admin organizational и собственным user-layer; system read-only. `edited_by` выводится из principal. B19 `R:1204–1261` требует локальный `X-Admin-Key` и повторяет tenant в рекурсивной CTE; отдельного human доступа нет. Чтение Admin всех tenant user-layer rules (`R:1008–1009,1038–1047`) соответствует текущей широкой UI проекции лишь условно: исходная матрица не определяет видимость содержимого чужого личного правила с достаточной точностью; решение нужно закрепить контрактом.
- MCP: production `memory-hub-mcp/Containerfile:33–41` запускает `src.main`, HTTP путь `memory-hub-mcp/src/main.py:146–160` подключает `create_http_middleware`; `MC/http_auth.py:19–86` использует JWKS, issuer, audience, RS256, проверяет exp/iat/nbf и required claims, Bearer без успешной проверки отвергает; `MC/authz.py:53–120` допускает отдельную API-key session только без Bearer. Слепого `verify_signature=False` в production пути не найдено. M13/M15/M17 и M25/M26/M44–M47 имеют технические checks, но это не human роль; `memory:admin` остаётся отдельным техническим полномочием.
- Auth: `memoryhub-auth/src/main.py:45–51` подключает `/admin` к тому же FastAPI app, что OAuth. `MA:29–35` проверяет только `X-Admin-Key`; `MA:66–263` позволяет list/get/create/update/rotate, иногда без обязательного tenant filter. `memoryhub-auth/openshift.yaml:195–220` публикует весь auth Service через edge Route, без route/path ограничения `/admin`; в проверенных манифестах нет NetworkPolicy, закрывающей этот HTTP путь. Любой, кто имеет общий admin key и сетевой доступ к публичному Route, минует человеческие правила BFF. Само получение ключа извне не доказано; риск связан с большой областью действия единственного ключа и отсутствием сетевого барьера.

## E. Security audit

Tenant/owner/project/object проверки в новых BFF routes в основном выполняются до чтения content и до мутации; граф и context повторно проверяют связанные nodes. Не найден подтверждённый межtenant BFF IDOR или прямой доступ User к Admin mutation. Нельзя распространить этот вывод на SQL race, живой proxy или Auth Route. Отдельно существенны: **S1** публичная technical admin поверхность Auth; **S2** `hidden_mentions`; **S3** допущение о доверенном локальном HTTP peer. `Auth` route может быть вызван независимо от BFF, но только с ключом; считать его human authorization нельзя.

Для полной security верификации нужны: проверка реального OpenShift Route/NetworkPolicy/RBAC port-forward и обработки forwarded headers proxy; PostgreSQL/pgvector тесты object visibility, graph connected query, pagination, cascade и batch rollback; проверка lifecycle HTTP streaming с DB session; проверка действительных конфигураций `ui_allowed_users/ui_admin_users/ui_tenant_id`, OAuth issuer/JWKS/audience и секретов. Эти проверки не выполнялись в текущем окружении.

## F. Тестирование

Запускалось из целевой рабочей копии с `-p no:cacheprovider` и без записи в БД:

| Набор | Команда (сокращённо) | Результат | Граница |
|---|---|---|---|
| BFF | `FRONTEND_DIST=... PYTHONPATH=memoryhub-ui/backend:src pytest memoryhub-ui/backend/tests -q -p no:cacheprovider` | **165 passed**, 1 warning | `TestClient` + подменённые DB/access/embedding; не real proxy/PostgreSQL. |
| Core services | `PYTHONPATH=src pytest tests/test_services -q -p no:cacheprovider` | **732 passed, 1 skipped**, 4 warnings | Преимущественно unit; pgvector SQL не проверен. |
| MCP | `PYTHONPATH=memory-hub-mcp:src pytest memory-hub-mcp/tests -q -p no:cacheprovider` | **707 passed, 2 skipped, 1 xfailed**, 17 warnings | JWT и tool checks тестируются локально; не production HTTP/cluster. |
| Auth | `PYTHONPATH=memoryhub-auth pytest memoryhub-auth/tests --ignore=memoryhub-auth/tests/integration -q -p no:cacheprovider` | **153 passed**, 16 warnings | Integration исключён, deployment не проверен. |

Здесь `pytest` — соответствующие существующие venv в основной рабочей копии. Локальные `127.0.0.1:5432` (PostgreSQL) и `:6379` (Valkey) ответили `connection refused`; совместимые DB/pgvector и Valkey integration не запускались. OpenShift, OAuth proxy, embedding service, browser E2E и публичные Routes не проверялись. Тест `test_stage22_adapters.py:58–69` заменяет и `get_access`, и `get_db`, а отдельные проверки отдают заранее заданные ответы MagicMock; успешные 165 тестов не подтверждают фактическое выполнение SQL predicate на PostgreSQL. `test_human_adapters.py:457–471` прямо показывает обнаруженный side channel.

Покрытие важных authorization границ по просмотренным тестам (`✓` означает наличие локального unit/HTTP-mock сценария, а не production доказательство):

| Группа | Positive User/Admin | Negative User/Admin | Cross-tenant/owner | Forged identity | Related object/rollback | Главный пробел |
|---|---|---|---|---|---|---|
| Session/bootstrap | ✓ / ✓ | ✓ / ✓ | tenant конфигурация ✓ | missing/duplicate/header role ✓ | — | Нет живого OAuth proxy/port-forward теста. |
| Projects/membership | ✓ / ✓ | ✓ / ✓ | agent membership и tenant SQL ✓ | server principal ✓ | last-admin/Core ✓ | Нет проверки PostgreSQL locking и реального roster. |
| Memory write/version/branch/relate/report | ✓ / ✓ в отдельных сценариях | ✓ / ✓ | foreign owner/scope ✓ | owner/actor spoof ✓ | обе вершины, entity mention ✓ | Нет DB race/transaction и embedding интеграции. |
| Context/graph/search | ✓ / ✓ | foreign personal/admin redaction ✓ | tenant/owner и hidden edges ✓ | зависимость `get_access` подменена | hidden versions/neighbours/explain ✓ | SQL, pgvector, pagination и proxy не исполнялись. |
| Bulk/moderation/export | ✓ / ✓ | User moderation и foreign cascade ✓ | mixed tenant/owner ✓ | principal подменён fixture | rollback `AsyncMock` ✓ | Нет PostgreSQL rollback/streaming under load. |
| OAuth clients/Auth admin | ✓ / ✓ BFF | scope/owner отрицательные ✓ | tenant check ✓ | header identity локально ✓ | — | Нет сетевого теста публичного Auth `/admin`, нет persisted human audit rotation. |
| MCP JWT/API key | technical positive ✓ | tampered/config negative ✓ | claims checks ✓ | JWT tamper ✓ | object/tool unit ✓ | Нет живого JWKS/issuer/audience/cluster теста. |

## G. Полная матрица E

`U/A`: ✓ — human BFF route и проверка есть; `часть` — часть UI сценария; `—` — матрица не выдаёт human право. `Sec`: `код` — guards видны в коде, живое исполнение не проверено; `S1/S2/S3` — дефект/риск из H. `T`: `unit` — подходящие unit/negative tests, `mock` — проверена лишь проекция с подменёнными зависимостями, `нет` — релевантного end-to-end нет. **VERIFIED COMPLETE не присваивается операциям, для которых критична неиспытанная DB/proxy граница.** Пункты с `NOT APPLICABLE` остаются существующими technical операциями, а не отсутствующими функциями.

| ID | Исходное требование E | Реализация | User | Admin | Security | Tests | Status | Evidence |
|---|---|---|---|---|---|---|---|---|
| B01 | Health без human роли | `GET /healthz` | — | — | liveness | unit | NOT APPLICABLE | R:165–167 |
| B02 | Публичные MCP/Auth URL для обеих ролей | `/api/public-config`; значения зависят от env | ✓ | ✓ | S3, env | unit | PARTIAL | R:254–268; config.py:30–39 |
| B03 | Граф User own/shared; Admin redacted metadata | Старый `/api/graph`, новый `/api/graph/all`, `/neighbourhood` | ✓ | ✓ | код | mock | NOT VERIFIED | R:276–345; G:152–290 |
| B04 | Поиск графа в human scope | `/api/graph/search`, `POST /api/search` | ✓ | ✓ | код | mock | PARTIAL | R:353–399; S:74–179 |
| B05 | Статистика + UI overview | `/api/stats`, `/nav-counts`; `/api/overview` нет | часть | часть | код | unit | PARTIAL | R:219–245,407–482 |
| B06 | Карточка с per-object redaction и context | `/api/memory/{id}`, `/context` | ✓ | ✓ | код | mock | NOT VERIFIED | R:490–579; C:51–180 |
| B07 | История каждой доступной версии | `/history` + context versions | ✓ | ✓ | код | mock | NOT VERIFIED | R:587–655; C:63–78 |
| B08 | Single/bulk soft delete, closure, audit | DELETE и batch `delete` | ✓ | ✓ | код | mock | NOT VERIFIED | R:663–719; H:592–634 |
| B09 | Клиенты: User bound, Admin tenant | `/api/clients` через Auth admin | ✓ | ✓ | S1 | unit | PARTIAL | R:803–812; MA:66–77 |
| B10 | Создание agent/client с server owner/tenant/scope | User user agent; Admin только service client | ✓ | часть | S1 | unit | PARTIAL | R:734–746,815–833 |
| B11 | Изменение клиента без расширения User прав | PATCH, owner recheck; Admin foreign scope expansion запрещено | ✓ | часть | S1 | unit | PARTIAL | R:749–762,836–856 |
| B12 | Ротация secret + key с owner guard | Только свой для User/Admin; не любой tenant client Admin | ✓ | часть | S1 | unit | PARTIAL | R:859–870; MA:204–236 |
| B13 | Ротация key с owner guard | Аналогично B12 | ✓ | часть | S1 | unit | PARTIAL | R:873–884; MA:239–263 |
| B14 | User own agents; Admin tenant identities; UI `/identities` | `/api/users` есть, `/api/identities` нет | часть | часть | код | unit | PARTIAL | R:892–971; UI `client.ts` identities |
| B15 | Видимые правила User/Admin | `/api/rules` tenant/layer/owner | ✓ | ✓ | видимость Admin требует решения | unit | PARTIAL | R:1003–1058 |
| B16 | Создание own user/organizational rule | POST, server owner/editor; system barred | ✓ | ✓ | код | unit | NOT VERIFIED | R:1061–1100 |
| B17 | Чтение правила с object guard | GET по ID | ✓ | ✓ | код | unit | NOT VERIFIED | R:1103–1125 |
| B18 | Copy-on-write rule update | PATCH, layer/owner immutable | ✓ | ✓ | код | unit | NOT VERIFIED | R:1128–1201 |
| B19 | Rule history техническая, tenant CTE | local + key; human grant нет | — | — | код | unit | NOT APPLICABLE | R:1204–1261 |
| B20 | Удаление разрешённого текущего правила | DELETE, owner/layer guard | ✓ | ✓ | код | unit | NOT VERIFIED | R:1276–1311 |
| B21 | Видимые contradiction reports | `/api/contradictions`, но UI `/review` нет | ✓ | часть | код | unit | PARTIAL | R:1319–1409 |
| B22 | Видимые contradiction counts | `/api/contradictions/stats`, nav | ✓ | часть | код | unit | PARTIAL | R:1350–1369,1412–1452 |
| B23 | Admin human decision, self-review guard | boolean `resolved` без approve/reject/history | — | часть | код | unit | BLOCKED | R:1455–1511; CS/memory.py:2153–2208 |
| M01 | MCP registration, без human grant | JWT/API-key session | — | — | technical | unit | NOT APPLICABLE | MC/http_auth.py:37–86; tools/register_session.py |
| M02 | Поиск обеими ролями | Core search + `POST /api/search` | ✓ | ✓ | код | mock | PARTIAL | S:74–179; CS/memory.py:1140–1230 |
| M03 | List/browse/export обеими ролями | Core list + browse/JSONL/CSV | ✓ | ✓ | код | mock | PARTIAL | H:728–974; X:34–122 |
| M04 | Read memory обеими ролями | detail + context | ✓ | ✓ | код | mock | NOT VERIFIED | R:490–579; C:51–180 |
| M05 | Similar с проверкой каждого hit | context similar | ✓ | ✓ | код | mock | NOT VERIFIED | C:126–139 |
| M06 | Relationships/provenance доступных nodes | context/graph | ✓ | ✓ | код | mock | NOT VERIFIED | C:90–112; G:121–140 |
| M07 | MCP guidance, UI нет | MCP tool | — | — | technical | unit | NOT APPLICABLE | tools/manage_graph.py |
| M08 | MCP reconstruct, UI нет | MCP tool | — | — | technical | unit | NOT APPLICABLE | tools/memory.py:435 |
| M09 | MCP status, UI нет | MCP tool | — | — | technical | unit | NOT APPLICABLE | tools/manage_session.py |
| M10 | Project focus history для обеих ролей | project detail + Valkey | ✓ | ✓ | код, Valkey не проверен | mock | NOT VERIFIED | H:259–289 |
| M11 | Project list для обеих ролей | `/api/projects` | ✓ | ✓ | код | mock | NOT VERIFIED | H:237–256 |
| M12 | Project detail/member list в human scope | `/api/projects/{name}`; MCP tenant/member guard | ✓ | ✓ | код | mock | NOT VERIFIED | H:259–289; tools/manage_project.py:264–290 |
| M13 | Memory write собственный/разрешённый scope | `/api/memories` + Core write | ✓ | ✓ | код | mock | NOT VERIFIED | H:433–463; CS/memory.py:66 |
| M14 | Version/update, bulk weight при UI contract | `/versions`; bulk weight нет | часть | часть | код | mock | PARTIAL | H:466–483,120–125 |
| M15 | Soft delete и batch c cascade | DELETE + bulk | ✓ | ✓ | код | mock | NOT VERIFIED | R:663–719; H:592–634 |
| M16 | Set MCP focus, UI нет | MCP session | — | — | technical | unit | NOT APPLICABLE | tools/manage_session.py |
| M17 | Relate обеими ролями при canWrite | single + bulk relate | ✓ | ✓ | код | mock | NOT VERIFIED | H:506–527,637–679 |
| M18 | Report при canWrite | `/api/memory/{id}/contradictions` | ✓ | ✓ | код | mock | NOT VERIFIED | H:530–541 |
| M19 | Admin review с disposition | Technical resolution; human decision не соединён | — | часть | technical | unit | BLOCKED | tools/manage_curation.py:423–470; R:1455–1511 |
| M20 | Собственное user-layer правило | MCP technical + BFF rules | ✓ | ✓ | код | unit | NOT VERIFIED | R:1013–1201; tools/manage_curation.py |
| M21 | Admin create project | BFF + Core | — | ✓ | код | mock | NOT VERIFIED | H:292–320; CS/project.py:165–210 |
| M22 | Admin add member, User нет | BFF direct project-admin; MCP membership admin | — | ✓ | код | mock | NOT VERIFIED | H:323–341; tools/manage_project.py:294–345 |
| M23 | User self-leave, Admin remove other | BFF split + Core last-admin | ✓ | ✓ | код | mock | NOT VERIFIED | H:344–365; CS/project.py:283–331 |
| M24 | Promotion только после отдельного решения | Technical direct promotion; human workflow нет | — | — | technical | unit | BLOCKED | tools/memory.py:647; CS/promotion.py |
| M25 | Graduate, UI нет | technical MCP + Core | — | — | technical | unit | NOT APPLICABLE | tools/memory.py:729–770 |
| M26 | Checkpoint, UI нет | technical MCP + Core | — | — | technical | unit | NOT APPLICABLE | tools/memory.py:594–675 |
| M27 | Entity backfill, UI нет | `memory:admin`, tenant SQL | — | — | technical | unit | NOT APPLICABLE | tools/backfill_entities.py:24–56 |
| M28 | User list entities/sources | BFF list + Core entity service | ✓ | — | S2 | mock | PARTIAL | H:1051–1139 |
| M29 | User merge; every source writable | BFF merge + Core | ✓ | — | код | mock | NOT VERIFIED | H:1026–1048,1212–1245 |
| M30 | User rename; linked sources writable | BFF rename + Core | ✓ | — | код | mock | NOT VERIFIED | H:1190–1209 |
| M31 | Admin search/browse metadata, personal hidden | BFF search/browse; direct technical regex отдельно | — | часть | код | mock | PARTIAL | S:44–179; H:728–974; CS/admin.py:104–209 |
| M32 | Admin quarantine с object grant | BFF bulk + Core | — | ✓ | код | mock | NOT VERIFIED | H:544–589; CS/admin.py:212–258 |
| M33 | Admin restore quarantine (не User undelete) | BFF bulk + Core | — | ✓ | код | mock | NOT VERIFIED | H:544–589; CS/admin.py:261–308 |
| M34 | Hard delete после второго Admin | Только direct technical MCP; approval нет | — | — | technical | unit | BLOCKED | CS/admin.py:311+; tools/admin_memory.py |
| M35 | Thread create без UI | MCP/Core thread | — | — | technical | unit | NOT APPLICABLE | tools/thread.py; MC/authz.py:320–423 |
| M36 | Thread append без UI | MCP/Core thread | — | — | technical | unit | NOT APPLICABLE | tools/thread.py; MC/authz.py:320–423 |
| M37 | Thread get без UI | MCP/Core thread | — | — | technical | unit | NOT APPLICABLE | tools/thread.py; MC/authz.py:320–423 |
| M38 | Thread list без UI | MCP/Core thread | — | — | technical | unit | NOT APPLICABLE | tools/thread.py; MC/authz.py:320–423 |
| M39 | Thread archive без UI | MCP/Core thread | — | — | technical | unit | NOT APPLICABLE | tools/thread.py; MC/authz.py:320–423 |
| M40 | Thread extract без UI | MCP/Core thread, внешняя model dependency | — | — | technical | unit | NOT APPLICABLE | tools/thread.py; MC/authz.py:320–423 |
| M41 | Thread fork без UI | MCP/Core thread | — | — | technical | unit | NOT APPLICABLE | tools/thread.py; MC/authz.py:320–423 |
| M42 | Thread share без UI | MCP/Core thread | — | — | technical | unit | NOT APPLICABLE | tools/thread.py; MC/authz.py:320–423 |
| M43 | Thread delete без UI | MCP/Core thread | — | — | technical | unit | NOT APPLICABLE | tools/thread.py; MC/authz.py:320–423 |
| M44 | Persona get без UI | MCP/Core persona, own identity | — | — | technical | unit | NOT APPLICABLE | tools/get_persona.py:63–85 |
| M45 | Persona compile без UI | MCP/Core persona, внешняя model dependency | — | — | technical | unit | NOT APPLICABLE | tools/compile_persona.py:67–86 |
| M46 | Persona add pin без UI | MCP/Core persona, own identity | — | — | technical | unit | NOT APPLICABLE | tools/edit_persona.py:60–98 |
| M47 | Persona list pins без UI | MCP/Core persona, own identity | — | — | technical | unit | NOT APPLICABLE | tools/edit_persona.py:60–98 |
| O01 | OAuth authorize/Openshift callback | Auth code + PKCE/OpenShift | — | — | technical | unit | NOT APPLICABLE | memoryhub-auth/src/routes/{authorize,openshift_callback}.py |
| O02 | OAuth client credentials | Auth `/token` | — | — | technical | unit | NOT APPLICABLE | memoryhub-auth/src/routes/token.py |
| O03 | OAuth authorization code exchange | Auth `/token` + redirect/PKCE | — | — | technical | unit | NOT APPLICABLE | memoryhub-auth/src/routes/token.py |
| O04 | OAuth refresh token | Auth `/token` + binding/revocation | — | — | technical | unit | NOT APPLICABLE | memoryhub-auth/src/routes/token.py |
| O05 | OAuth token exchange | Auth `/token` + tenant/scope restriction | — | — | technical | unit | NOT APPLICABLE | memoryhub-auth/src/routes/token.py; token_exchange.py |
| O06 | OAuth metadata/JWKS | Auth well-known routes | — | — | technical | unit | NOT APPLICABLE | memoryhub-auth/src/routes/well_known.py |
| O07 | Client list только через BFF human guard | Auth admin list, публичный Route | ✓ | ✓ | S1 | unit | PARTIAL | MA:66–77; R:803–812; openshift.yaml:208–220 |
| O08 | Client create только через BFF human guard | Auth admin create, публичный Route | ✓ | часть | S1 | unit | PARTIAL | MA:80–149; R:815–833 |
| O09 | Auth client detail technical | Внутренний для BFF, публичный Route | — | — | S1 | unit | NOT APPLICABLE | MA:152–166; R:749–762 |
| O10 | Client update через BFF human guard | Auth admin PATCH, публичный Route | ✓ | часть | S1 | unit | PARTIAL | MA:169–201; R:836–856 |
| O11 | Client secret rotation через BFF | Auth admin POST, публичный Route | ✓ | часть | S1 | unit | PARTIAL | MA:204–236; R:859–870 |
| O12 | API key rotation через BFF | Auth admin POST, публичный Route | ✓ | часть | S1 | unit | PARTIAL | MA:239–263; R:873–884 |
| O13 | Internal API key validation, без human роли | `X-Service-Key` | — | — | technical | unit | NOT APPLICABLE | memoryhub-auth/src/routes/internal.py |
| O14 | Auth liveness, без human роли | `GET /healthz` | — | — | technical | unit | NOT APPLICABLE | memoryhub-auth/src/routes/health.py |

## H. Дефекты и находки

| ID / severity | Место и операция | Сценарий; ожидаемое → фактическое | Тест / рекомендуемое изменение |
|---|---|---|---|
| S1 **HIGH** | `memoryhub-auth/openshift.yaml:195–220`, `memoryhub-auth/src/main.py:50`, `MA:29–35,66–263`; B09–B13/O07–O12 | Публичный Auth Route маршрутизирует `/admin/*`; обладатель общего `X-Admin-Key` может указать произвольный tenant/owner и вызвать управление клиентами, минуя BFF User/Admin/object guards. Матрица E требует только service-to-service Auth admin. Ключ обязателен, поэтому доступ без секрета не доказан. | `memoryhub-auth/tests/test_admin.py` проверяет ключ, но нет сетевого теста на закрытие `/admin`. Ограничить маршрут `/admin/*` на уровне сети/внутреннего endpoint и сохранить BFF проверки; проверить реальную Route policy. |
| S2 **MEDIUM** | `H:986–1004,1142–1180`; M28/entity detail | User, имеющий доступ к entity, получает `hidden_mentions` из числа недоступных same-tenant sources. Ожидалось отсутствие сведений о чужих объектах; фактически раскрывается их количество. | `test_human_adapters.py:457–471` утверждает эту выдачу. Убрать aggregate либо считать только авторизованные sources, обновив контракт/тесты. |
| S3 **MEDIUM, условный** | `A:48–68`; session | Любой caller, реально достигший BFF по loopback, может задать один `x-forwarded-user` из admin allowlist. Внешний путь через proxy не подтверждён, но единственным доказательством proxy является адрес peer. | Unit тесты используют подставленный header; нет live proxy/port-forward проверки. Проверить ingress, network namespace и proxy header sanitization; при необходимости добавить проверяемое proxy assertion. |
| F1 **MEDIUM** | `S:39,87–110,123–179`; B04/M02/M31 | UI разрешает rerank/explain и показывает retrieval stages; `rerank` игнорируется, `retrieval` и funnel counts константны, post-limit фильтры могут недобрать страницу. Ожидалась точная проекция имеющегося Core результата; выдача описывает другой процесс. | `test_stage22_adapters.py:244–291` проверяет scope, не семантику диагностики. Отделить недоступные метрики от фактических и согласовать фильтрацию до лимита с Core contract. |
| F2 **MEDIUM** | `H:817–832,910,970`, `G:103–112`; M03/B03 | UI `mode=semantic` для browse/graph и near-duplicate facet выглядят доступными; код применяет `ILIKE` и возвращает `None` для near-duplicate. | Нет live pgvector/browse contract теста. Обозначить функции как unsupported либо адаптировать только при подтверждённой существующей Core операции. |
| F3 **MEDIUM** | `memoryhub-ui/Containerfile:10,16,36–37`; Stage 2.2 UI adapters | Деплой целевой ветки собирает старый Frontend: новые UI calls существуют только в ref `memoryhub-ui`. Ожидалась интеграция существующего UI; фактически эти маршруты в данном образе не используются. | Browser E2E не выполнялся. Согласовать объединение веток/сборку после отдельного решения без изменения Frontend в этом аудите. |
| F4 **MEDIUM** | `R:407–482,892–971`; B05/B14 | UI ref `memoryhub-ui` вызывает `/overview` и `/identities`, BFF отдаёт лишь `/stats` и `/users`; часть представленной UI функциональности недоступна через ожидаемый adapter. | Нет end-to-end UI теста. Сопоставить существующие данные с UI контрактом при следующем этапе. |
| F5 **MEDIUM, контракт** | `R:734–746,859–884`; B10–B13 | E допускает Admin управлять tenant clients; BFF создаёт для Admin только service clients и ротирует только собственные. Права сознательно сужены, потому что безопасное присвоение владельца чужому user client не определено; это функциональный разрыв, не лишнее полномочие. | `test_stage2_security.py:253–345` проверяет запреты. Уточнить trusted owner/client grant; не расширять права автоматически. |
| F6 **MEDIUM, контракт** | `R:1455–1511`, `CS/memory.py:2153–2208`; B23/M19 | `resolved: bool` не передаёт approve/reject, explanation, review history и последствия для memory. Technical Core actions — отдельный путь, не human review. | Тесты B23 проверяют guards, не полный workflow. Сначала утвердить contract; не подменять decision флагом. |
| F7 **LOW / NOT VERIFIED** | `X:61–74,97–120`; M03 export | Поток читает offset-страницы в процессе ответа без снимка; при конкурентной записи строки могут повториться/пропасть. Без живой БД это риск, а не воспроизведённый дефект. | Тесты export mock одной страницы. Проверить в PostgreSQL и определить требуемую стабильность выгрузки. |
| F8 **MEDIUM** | `R:859–884`, `MA:204–263`; B12–B13/O11–O12 | Ротация секретов проходит owner/tenant guard, но не создаёт сохраняемый human audit event: BFF сразу проксирует запрос, Auth только пишет в обычный log. Матрица E требует audit инициатора. | Тесты проверяют запреты и ответ, не наличие audit row. Сохранять событие с human actor, client и tenant без plaintext секретов в согласованном журнале. |

## I. Блокеры и неподтверждённые требования

1. **Security blocker S1:** service key защищает прямой Auth API, но публичный Route противоречит ограничению service-to-service; реальная network policy и путь proxy не проверены. S3 требует отдельного live подтверждения trust boundary.
2. **B23/review queue:** `resolved` не есть approve/reject, отсутствуют обязательное explanation, review history и надёжное изменение memory; `/api/review` UI contract отсутствует. M19 содержит четыре технических disposition, но не обеспечивает человеческий approval process.
3. **Promotion proposal M24:** прямой MCP promotion существует, UI request/withdraw/decision не существует в текущем Backend. Его нельзя выдавать как human action без нового workflow.
4. **M34:** технический hard delete не имеет независимого второго Admin approval. Прямого human adapter нет; исходная UI процедура заблокирована.
5. **Bulk weight M14:** Core умеет обновлять одну версию, но нет подтверждённой атомарной batch операции. User soft-delete restore UI не равен Admin quarantine restore M33; отдельной существующей Core операции undelete не найдено.
6. **Access-log/usage:** `AuditLog` частично хранит события, context считает `memory.read`, но `/memory/{id}/access-log`, `/memory/{id}/usage`, `/usage/summary` не реализованы. Они присутствуют в UI ref, но не являются автоматически разрешёнными новыми бизнес-функциями матрицы E; требуются отдельные требования к данным/проекции.
7. **Live integration:** PostgreSQL/pgvector, Valkey, embedding, OAuth proxy, OpenShift Route, API key/JWKS настройка и browser E2E отсутствуют. Выполнение object SQL/transaction и фактическая закрытость служебных путей **NOT VERIFIED**.
8. **Неоднозначность:** объём видимости Admin для чужих user-layer curation rules и допустимый набор Admin OAuth client operations в E недостаточно конкретен для безопасного расширения. Обе области оставлены частичными.

## J. Рекомендуемый порядок исправлений

1. Закрыть публичную сеть к Auth `/admin/*` или вынести технический маршрут на внутреннюю поверхность; проверить реальный OpenShift deployment и сохранение BFF owner/tenant checks.
2. Проверить OAuth proxy header rewriting, прямой доступ к pod/port-forward и session expiration в целевой среде. Устранить найденный обход, если подтвердится.
3. Убрать `hidden_mentions` по недоступным объектам; покрыть смешанные owner/project/tenant на PostgreSQL.
4. Проверить на PostgreSQL транзакционность delete/relate/moderation, graph/context/search фильтры и export streaming/pagination. Только после этого повышать `NOT VERIFIED` до `VERIFIED COMPLETE`.
5. Согласовать существующие `/overview` и `/identities` UI adapters и интеграцию Frontend ветки с Backend; не считать старую сборку полноценным UI этапа 2.2.
6. Уточнить безопасный Admin grant на user clients и правила видимости user-layer curation. Добавить сохраняемый human audit ротации без секретов. Разобрать реальные Search/browse contracts без выдуманных метрик.
7. Отдельно утвердить contracts B23/review, promotion proposal, второго Admin hard-delete, bulk weight, User undelete и access-log/usage. До решения оставить их заблокированными, не имитировать существующими endpoints.

## K. Итоговый вердикт

**AUDIT FAILED.** Подтверждён **HIGH** дефект границы service-to-service Auth admin (S1), **MEDIUM** side channel entity (S2), и существенные функциональные пробелы. Код BFF в основном разделяет User/Admin и повторно проверяет доступ к связанным memory objects, но полный переход по исходной матрице E не завершён. Успешные unit-тесты не заменяют проверку живых PostgreSQL/pgvector, OAuth proxy и OpenShift. Ни одной бизнес-операции, зависящей от этих границ, не присвоен статус `VERIFIED COMPLETE` только по зелёному HTTP/unit-тесту.
