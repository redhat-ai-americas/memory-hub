# How Information Enters an Agent's Context

At inference time, a model sees one undifferentiated stream of tokens. It cannot tell which tokens came from memory, which from a retrieved document, which from a tool call, which the user typed. Every source feels different to us; to the model, they're all just tokens in a sequence.

That's why context assembly is the hard problem. The model's output quality is bounded by what assembly chose to include.

```
                HOW INFORMATION ENTERS AN AGENT'S CONTEXT

  ┌──────────────────────────────────────────────────────────────────────┐
  │                        SOURCE SYSTEMS                               │
  │                   (where knowledge lives)                           │
  └──────────────────────────────────────────────────────────────────────┘

  ┌─────────────────┐       ┌─────────────────┐       ┌─────────────────┐
  │  SYSTEM PROMPT   │       │  AGENT MEMORY   │       │ SESSION HISTORY │
  │                 │       │                 │       │                 │
  │  Instructions,  │       │  Experiential:  │       │  Prior turns in │
  │  persona, rules │       │  decisions made,│       │  this conver-   │
  │                 │       │  preferences    │       │  sation (com-   │
  │  Set once at    │       │  discovered,    │       │  pressed as it  │
  │  session start  │       │  outcomes       │       │  grows)         │
  │                 │       │  observed       │       │                 │
  │  from: config,  │       │                 │       │  from: the      │
  │  CLAUDE.md,     │       │  Accumulated    │       │  conversation   │
  │  agent rules    │       │  across sessions│       │  itself         │
  │                 │       │                 │       │                 │
  │                 │       │  from: MemoryHub│       │                 │
  │                 │       │  or equivalent  │       │                 │
  └────────┬────────┘       └────────┬────────┘       └────────┬────────┘
           │                         │                          │
           │  prepend at             │  inject at session       │  accumulate
           │  session start          │  start; search           │  each turn
           │                         │  on demand               │
           ▼                         ▼                          ▼
  ┌──────────────────────────────────────────────────────────────────────┐
  │                                                                      │
  │                         CONTEXT WINDOW                               │
  │                                                                      │
  │   ┌────────────────────────────────────────────────────────────┐     │
  │   │  You are a helpful assistant that...                       │     │
  │   │  User prefers Podman over Docker. Last sprint decided...   │     │
  │   │  [user]: Fix the deploy script to handle existing ns...    │     │
  │   │  [assistant]: I'll check the current script. ...           │     │
  │   │  The deployment guide §4.2 says to create the SA first... │     │
  │   │  Results for "openshift namespace creation": ...           │     │
  │   │  Entity: Patient | Type: Person | Role: Primary ...        │     │
  │   │  $ oc get pods -n memoryhub                                │     │
  │   │  NAME            STATUS    RESTARTS   AGE                  │     │
  │   │  mcp-pod-1       Running   0          3d                   │     │
  │   │  [user]: Now add the SCC grant for the service account     │     │
  │   └────────────────────────────────────────────────────────────┘     │
  │                                                                      │
  │   No boundaries exist inside this box. The model sees one            │
  │   stream of tokens. It cannot tell which came from memory,           │
  │   which from RAG, which from a tool call, which the user typed.      │
  │                                                                      │
  └──────────────────────────────┬───────────────────────────────────────┘
                                 │
           ▲                     │                          ▲
           │  retrieve by        │                          │  execute
           │  similarity         │                          │  mid-turn
           │                     │                          │
  ┌────────┴────────┐            │               ┌─────────┴─────────┐
  │      RAG        │            │               │   TOOL RESULTS    │
  │                 │            │               │                   │
  │  Pre-existing   │            │               │  File contents,   │
  │  document       │            │               │  command output,  │
  │  chunks matched │            │               │  API responses,   │
  │  by vector      │            │               │  computed data    │
  │  similarity     │            │               │                   │
  │                 │            │               │  from: MCP tools, │
  │  from: manuals, │            │               │  shell, APIs,     │
  │  policies, KBs  │            │               │  file system      │
  └─────────────────┘            │               └───────────────────┘
                                 │
           ▲                     │                          ▲
           │  query at           │                          │  embed or
           │  runtime            │                          │  query
           │                     │                          │
  ┌────────┴────────┐            │               ┌─────────┴─────────┐
  │     SEARCH      │            │               │     ONTOLOGY      │
  │                 │            │               │                   │
  │  Live lookup    │            │               │  Domain structure:│
  │  of existing    │            │               │  entity types,    │
  │  information    │            │               │  hierarchies,     │
  │  at query time  │            │               │  named relations  │
  │                 │            │               │                   │
  │  from: web,     │            │               │  from: knowledge  │
  │  indices, DBs   │            │               │  graphs, schemas, │
  │                 │            │               │  taxonomies       │
  └─────────────────┘            │               └───────────────────┘
                                 │
                                 ▼
                          ┌────────────┐
                          │  RESPONSE  │
                          └────────────┘
```

## Why the distinction matters (even though the model can't see it)

| Source | How it gets knowledge | Characteristic |
|---|---|---|
| **Memory** | Learned from **doing** | Accumulates across sessions |
| **RAG** | Retrieved from **documents** | Matches against a static corpus |
| **Search** | Found by **looking** | Discovers existing live information |
| **Ontology** | Defined by **modeling** | Encodes structural domain knowledge |
| **Tools** | Obtained by **acting** | Produces ephemeral real-time data |

Context assembly is the policy layer that decides what gets in, what stays out, and how much space each source gets. The model's output quality is bounded by what assembly chose to include. 100% of what it needs, 0% of what it doesn't.

## Where MemoryHub fits

MemoryHub owns the **agent memory** lane: experiential knowledge persisted across sessions, governed by scoped access control, and recalled to shape future behavior. It does not replace RAG, search, ontology, or tool infrastructure. Those systems solve different problems and enter context through different mechanisms. MemoryHub solves the problem of what agents carry forward from experience.

For more on the distinction between agent memory and other knowledge systems, see [What Agent Memory Really Is](what-is-agent-memory.md).
