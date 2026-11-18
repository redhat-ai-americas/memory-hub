# Этап 2.2 — human adapters и оставшиеся интеграционные пробелы

Дата: 2026-11-18. Основание: `MemoryHub-User-Admin-audit-2026-11-17.md`, разделы A–G и матрица E; существующие UI вызовы из `memoryhub-ui`.

## A. Git и сохранность

- Рабочая ветка: `backend-admin-user-roles` в отдельной рабочей копии `/Users/kromashk/ui for memoryhub/memory-hub-backend-admin-user-roles`. Основная папка была на `ui-user-role` с незакоммиченными изменениями Frontend; они оставлены без изменений.
- Начальный и конечный HEAD: `c34a15c3a83378fffccd647fe6884681b60ff37a` (`Add human User and Admin backend adapters`). Целевая рабочая копия до работы была чистой. После работы изменены только Backend, Core, тесты и этот отчёт.
- Commit и push не выполнялись. Frontend не изменён.
- Изменённые существующие файлы: `memoryhub-ui/backend/src/human_adapters.py`, `main.py`, `routes.py`; `memoryhub-ui/backend/tests/test_human_adapters.py`, `test_routes.py`, `test_stage2_security.py`; `src/memoryhub_core/services/graph.py`, `memory.py`; `tests/test_services/test_graph_service.py`.
- Новые файлы: `memoryhub-ui/backend/src/memory_context.py`, `graph_adapters.py`, `search_adapter.py`, `export_adapter.py`; `memoryhub-ui/backend/tests/test_stage22_adapters.py`; этот отчёт.

## B. UI-to-Backend mapping

| UI operation | Existing Backend operation | BFF endpoint | Matrix E ID | Status / missing part |
|---|---|---|---|---|
| Memory detail/context | Core history, similarity, relationships; BFF detail/history | `GET /api/memory/{id}/context` | B06–B07, M04–M06 | Добавлен; все версии, ветви, соседи и similar проходят отдельную проверку. Usage/access-log остаются отдельными UI вызовами без adapter. |
| Full graph | B03 graph over `MemoryNode`/`MemoryRelationship` | `GET /api/graph/all` | B03, M06 | Добавлен; доступные nodes и edges, безопасные counts и UI shape. |
| Local graph | Core graph relationships/neighbour traversal; B03 graph | `GET /api/graph/neighbourhood` | B03, M06 | Добавлен bounded BFS с проверкой каждого шага и соседа. |
| Search playground | Core `search_memories` / `search_memories_with_focus` | **`POST /api/search`** | B04, M02, M31 | Добавлен по фактическому UI вызову. В задании указан GET, но UI вызывает POST. Нет Core trace для точных pipeline stages/funnel и нет сконфигурированного reranker. |
| Bulk delete | B08/M15 + Core `collect_delete_nodes` | `POST /api/memories/bulk` (`delete`) | B08, M15 | Добавлен; полная проверка closure, единый SQL update/commit, audit. |
| Bulk relate | M17 Core `create_relationship` | `POST /api/memories/bulk` (`relate`) | M17 | Добавлен; обе вершины и все источники проверяются до записи; Core поддерживает вызов с `commit=False` в общей транзакции. |
| Bulk quarantine / restore | M32–M33 Core | `POST /api/memories/bulk` | M32–M33 | Уже сделано в Этапе 2.1; не переписано. Это Admin moderation restore, не User soft-delete restore. |
| Bulk weight | M14 Core single `update_memory` | Нет безопасного bulk adapter | M14 | BLOCKED: Core фиксирует каждое обновление отдельно; цикл нарушил бы all-or-nothing. |
| Browse facets / entity projection | M03/Core memory rows, reports, mentions | `GET /api/memories/browse` | M03, M31; U06/A20 | Дополнены domains, supported flags и связанные entities; дочерние объекты фильтруются по human grant. `semantic` в browse по-прежнему text fallback. |
| User JSONL / Admin CSV | M03 + BFF browse | `GET /api/memories/export` | M03, M31; U08/A20 | Добавлен постраничный экспорт; User row recheck + content, Admin только metadata. |

`memoryhub-ui/frontend/src/api/client.ts` подтверждает URLs и методы; `src/types/index.ts` задаёт структуры `MemoryContext`, `GraphAll`, `GraphNeighbourhood`, `SearchResponse` и `BrowseResponse`. UI `browseParams` передаёт фильтры таблице, графу и экспорту. Дополнительных Frontend операций не добавлено.

## C. Реализованные adapters и разрешения

| Endpoint | Core/данные | User | Admin | Проверки и проекция |
|---|---|---|---|---|
| `GET /api/memory/{id}/context` | `get_memory_history`, `get_similar_memories`, memory/relationship/report/audit models | Свои personal, доступные project и shared | Tenant metadata personal без текста; content только в явно разрешённых human shared scopes | Seed tenant/read; каждая версия, ветвь, связь, similar hit и parent отдельно проверяются. Hidden object не появляется даже в omitted count. |
| `GET /api/graph/all` | B03 graph и Core relationship model | Свои/разрешённые nodes | Tenant metadata, personal stub/content скрыты | SQL tenant/human conditions до limit/count; edge только между выбранными доступными nodes; `total`, `left_out`, degree и orphan считаются по этой проекции. `max_nodes≤1500`. |
| `GET /api/graph/neighbourhood` | Core graph primitives/relations | Разрешённый focus и каждый сосед | Те же независимые правила Admin | Depth 1–3; каждый фронтир состоит только из доступных nodes, скрытые nodes не расширяют обход; edges и provenance/conflicts из разрешённого подграфа. |
| `POST /api/search` | `search_memories`, `search_memories_with_focus` | Direct human grants, bound agents только для personal | Explicit shared scopes; personal content не ищется | Tenant/owner/project фильтр в Core, затем SQL rehydration и per-hit check; snippets, explain и counts строятся только из разрешённой выдачи. `identity`/`project` являются сужающими фильтрами, не полномочиями. |
| `POST /api/memories/bulk` (`delete`) | B08/M15 `collect_delete_nodes` | Собственная personal и разрешённый project delete | Только явный moderation/project/author grant | Все seeds, версии и потомки проверяются до одного UPDATE; tenant и relationship boundary; audit в той же транзакции. |
| `POST /api/memories/bulk` (`relate`) | M17 `create_relationship` | Только обе writable вершины в совместимом scope | Только обе writable shared вершины по независимому grant | Preflight target/all sources, same-scope/personal-owner check, duplicate check, `commit=False`, общий commit/rollback и audit. |
| `GET /api/memories/export` | M03 через существующий BFF browse | JSONL только по доступным объектам; `mine=true` сужает до своих | CSV только metadata, включая personal без текста | Фильтры совпадают с browse; первая страница проверяется до streaming; каждая User строка повторно авторизуется. CSV formula cells экранируются. |

В старых `GET /api/graph` и `GET /api/memory/{id}` теперь исключены invalidated relationships; старый `GET /api/memory/{id}/history` повторно исключает удалённые версии. Existing Projects, memberships, writes, reports, entities, moderation и single delete сохранены.

## D. Authorization и security

- Все новые маршруты используют `AccessDep` и verified OAuth proxy principal; роль, tenant и actor не берутся из request. User и Admin политики независимы. `identity`, `project`, `scope`, `actor` и другие UI фильтры не расширяют grant.
- IDOR: seed/focus/target/source IDs проверяются по tenant и object permission. Контекст и граф фильтруют каждый связанный объект до сериализации. Admin personal content/stub не выдаётся; graph/search не раскрывают скрытые snippets или скрытые edge counts.
- `SearchResponse.explain` не различает скрытый и отсутствующий ID. `candidates` и прочие UI counts отражают только разрешённую выдачу, а не внутренний Core recall pool. Это безопасная, но неполная диагностическая проекция.
- Bulk delete и relate выполняют preflight до мутаций, используют один commit и rollback при сбое. Core `create_relationship` сохранил default commit для прежних клиентов и получил внутренний `commit=False` для batch. Bulk weight и User soft-delete restore не предоставлены как небезопасные замены.
- Остаточный риск: PostgreSQL/pgvector SQL и конкурентные изменения при постраничном export не проверены в живой среде; export не обещает repeatable-read snapshot. Connected graph ranking может быть дорогим на большом tenant. В browse `semantic` остаётся text fallback, `near_duplicate` facet не вычисляется.

## E. Тестирование

| Проверка | Итог |
|---|---|
| BFF: `pytest memoryhub-ui/backend/tests -q` с `FRONTEND_DIST` основной папки и `PYTHONPATH` целевой копии | **165 passed**; включая Stage 1/2/2.1 и 24 новых теста Stage 2.2 |
| Core: `pytest tests/test_services -q` | **732 passed, 1 skipped** |
| MCP: `pytest memory-hub-mcp/tests -q` | **707 passed, 2 skipped, 1 xfailed** |
| OAuth: `pytest memoryhub-auth/tests --ignore=memoryhub-auth/tests/integration -q` | **153 passed** |
| Ruff по изменённым Backend/Core/test файлам; `git diff --check` | Passed |
| Локальные PostgreSQL:5432 и Valkey:6379 | Connection refused; совместимые DB/pgvector и Valkey integration tests не выполнены |
| OpenShift, живой OAuth proxy, embedding service, browser E2E | Не проверялись в этом окружении |

`FRONTEND_DIST` нужен только тестовой среде: чистая рабочая копия не содержит игнорируемый `frontend/dist`. При отсутствии сборки прежний тест для несуществующего `/api/auth/login` получает 404 вместо 405 из-за отсутствия SPA fallback; это не изменение Backend authorization.

## F. Матрица E — затронутые статусы

| ID | Статус | Основание |
|---|---|---|
| B03–B04 | PARTIAL | Graph adapters есть; search выполняет Core retrieval, но полный UI pipeline trace/rerank и живой pgvector не подтверждены. |
| B06–B07 | COMPLETE (код/unit) | Context, history и per-object redaction подключены; live DB ещё не проверена. Отдельные usage/access-log UI calls остаются вне этих двух операций. |
| B08 | COMPLETE (код/unit) | Single и bulk delete используют Core closure и объектный preflight. |
| M02 | PARTIAL | Human search есть, Core trace/funnel отсутствует. |
| M03 | PARTIAL | Browse/export проекции добавлены; semantic browse и near-duplicate facet не поддержаны текущим адаптером. |
| M04–M06 | COMPLETE (код/unit) | Context/similar/relations и graph проекции с проверкой каждого returned object. |
| M14 | PARTIAL / bulk weight BLOCKED | Single version adapter остаётся; атомарного Core batch update нет. |
| M15, M17 | COMPLETE (код/unit) | Bulk delete/relate добавлены к single операциям. |
| M31 | PARTIAL | Admin human search и metadata-only browse/CSV есть; технический admin/regex Core контракт не переводится в произвольное human право. |
| M32–M33 | COMPLETE (ранее) | Admin quarantine/restore из Этапа 2.1 без ослабления. |
| B23, M19, M24, M34 | NOT APPLICABLE к реализации Этапа 2.2 | Требуют отдельных контрактных решений, перечислены ниже. |

## G. Остаточные блокеры

1. **B23/review queue:** `resolved: boolean` не выражает approve/reject, объяснение и историю решений. Не реализовывалось в этом этапе.
2. **Promotion proposal:** M24 выполняет непосредственное promotion, а UI обещает заявку и отдельное решение. Без workflow нельзя выдавать прямой human adapter.
3. **Second Admin hard-delete approval:** M34 не содержит подтверждения независимым вторым Admin. Прямой human вызов оставлен закрытым.
4. **Bulk weight:** M14 фиксирует версии по одной; безопасный all-or-nothing batch на текущем Core контракте отсутствует. **User soft-delete restore** также не равен M33 Admin quarantine restore. Bulk promote не создавался.
5. **UI contracts:** Search playground ожидает настоящий pipeline trace/funnel/rerank; Core search возвращает итоговый список и score. Browse semantic filter сейчас text fallback, `near_duplicate` facet не сохранён. `/memory/{id}/access-log`, `/memory/{id}/usage` и часть других UI маршрутов нуждаются в отдельном подтверждении по матрице E и не были выданы этим этапом.
6. **Live integration:** PostgreSQL/pgvector, OpenShift/OAuth proxy, Valkey, embedding service и browser E2E не подтверждены. SQL pagination, counts, graph connected ranking, export и transaction boundaries требуют проверки в совместимой среде.

## H. Вердикт

**PARTIALLY COMPLETED.** Подтверждённые adapters context, graph, search, bulk delete/relate и export подключены, human object authorization проверена unit/regression тестами. Этап не объявляется завершённым из-за блокированного bulk weight, неполного Search/browse UI контракта и отсутствия живой PostgreSQL/pgvector и OAuth proxy проверки. Отдельные B23/review/promotion/hard-delete решения сознательно не подменялись существующими endpoints.
