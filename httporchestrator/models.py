from enum import Enum
from typing import Any, Callable, Dict, List, Union

from pydantic import BaseModel, Field

VariablesMapping = Dict[str, Any]
Headers = Dict[str, str]
Cookies = Dict[str, str]
HookCallable = Callable[[Dict[str, Any]], Any]
HookItem = Union[HookCallable, Dict[str, HookCallable]]
Hooks = List[HookItem]
Validators = List[Dict]


class MethodEnum(str, Enum):
    GET = "GET"
    POST = "POST"
    PUT = "PUT"
    DELETE = "DELETE"
    HEAD = "HEAD"
    OPTIONS = "OPTIONS"
    PATCH = "PATCH"


class ConfigData(BaseModel):
    name: str
    verify: bool = False
    base_url: str = ""
    add_request_id: bool = True
    log_details: bool = True
    variables: VariablesMapping = {}
    export: List[str] = []
    path: str = None


class StepData(BaseModel):
    class Config:
        arbitrary_types_allowed = True

    name: str
    request: Any = None  # RequestSpec (imported from http_models to avoid circular)
    workflow: Any = None  # reference to another HttpRunner subclass
    variables: VariablesMapping = {}
    setup_hooks: Hooks = []
    teardown_hooks: Hooks = []
    extract: VariablesMapping = {}
    export: List[str] = []
    validators: Validators = Field([], alias="validate")
    validate_script: List[str] = []
    retry_times: int = 0
    retry_interval: int = 0  # sec


class Workflow(BaseModel):
    config: ConfigData
    steps: List[StepData]


class WorkflowTiming(BaseModel):
    start_at: float = 0
    start_at_iso_format: str = ""
    duration: float = 0


class WorkflowIO(BaseModel):
    config_vars: VariablesMapping = {}
    export_vars: Dict = {}


class StepResult(BaseModel):
    """Step result data, each step corresponds to one request or one workflow."""

    name: str = ""
    step_type: str = ""
    success: bool = False
    data: Any = None  # SessionData or List[StepResult]
    elapsed: float = 0.0
    content_size: float = 0
    export_vars: VariablesMapping = {}
    attachment: str = ""


class StepProtocol(object):
    def name(self) -> str:
        raise NotImplementedError

    def type(self) -> str:
        raise NotImplementedError

    def struct(self) -> StepData:
        raise NotImplementedError

    def run(self, runner) -> StepResult:
        raise NotImplementedError


class WorkflowSummary(BaseModel):
    name: str
    success: bool
    case_id: str
    time: WorkflowTiming
    in_out: WorkflowIO = {}
    log: str = ""
    step_results: List[StepResult] = []
