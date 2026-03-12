# httporchestrator — HTTP Workflow Orchestration Engine

## Architecture

httporchestrator models every test scenario as a `Workflow`: an ordered list of steps
controlled by a shared `Config`.

```
Config  ──▶  Workflow
               ├── RunRequest("...")
               ├── RunRequest("...")
               └── RunWorkflow(...)
```

### Step types

| Class | File | Purpose |
|-------|------|---------|
| `RunRequest` | [step_request.py](step_request.py) | Single HTTP request |
| `RunWorkflow` | [step_workflow.py](step_workflow.py) | Reference another workflow |
| `ConditionalStep` | [step_request.py](step_request.py) | Wraps a step with a predicate — skips if condition is false |

### Key modules

| Module | Purpose |
|--------|---------|
| [runner.py](runner.py) | Test executor — runs steps, collects results (uses `httpx.Client` directly) |
| [client.py](client.py) | Utility functions for request/response recording |
| [response.py](response.py) | Response extraction & validation |
| [comparators.py](comparators.py) | Assertion functions for validators |
| [models.py](models.py) | Workflow-domain Pydantic models |
| [http_models.py](http_models.py) | HTTP recording Pydantic models |
| [expressions.py](expressions.py) | Variable/function resolution, URL building |
| [config.py](config.py) | Fluent `Config` builder |

## Writing tests

All test classes inherit from `HttpRunner`:

```py
from httporchestrator import HttpRunner, Config, RunRequest

class MyWorkflow(HttpRunner):
    config = Config("example workflow")
    steps = [
        RunRequest("get users")
        .get("/api/users")
        .validate()
        .assert_equal("status_code", 200),
    ]
```

## Running

```bash
python -B -m pytest tests/ -q
```
