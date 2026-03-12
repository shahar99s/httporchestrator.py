"""HTTP recording models — request/response data captured during execution."""

from typing import Any, Callable, Dict, List, Union

from pydantic import BaseModel

from httporchestrator.models import Cookies, Headers, MethodEnum


class RequestTemplate(BaseModel):
    """HTTP request template used to define a step's request."""

    class Config:
        arbitrary_types_allowed = True

    method: MethodEnum
    url: Any = ""  # str or callable
    params: Dict[str, Union[str, Callable]] = {}
    headers: Dict[str, Union[str, Callable]] = {}
    req_json: Any = None  # dict, list, str, or callable
    data: Union[str, Dict[str, Any]] = None
    cookies: Cookies = {}
    timeout: float = 120
    allow_redirects: bool = True
    verify: bool = False
    upload: Dict = {}  # used for upload files


class RequestMetrics(BaseModel):
    content_size: float = 0
    response_time_ms: float = 0
    elapsed_ms: float = 0


class AddressData(BaseModel):
    client_ip: str = "N/A"
    client_port: int = 0
    server_ip: str = "N/A"
    server_port: int = 0


class RequestData(BaseModel):
    method: MethodEnum = MethodEnum.GET
    url: str
    headers: Headers = {}
    cookies: Cookies = {}
    body: Union[str, bytes, List, Dict, None] = {}


class ResponseData(BaseModel):
    status_code: int
    headers: Dict
    cookies: Cookies
    encoding: Union[str, None] = None
    content_type: str
    body: Union[str, bytes, List, Dict, None]


class RequestResponseRecord(BaseModel):
    request: RequestData
    response: ResponseData


class SessionData(BaseModel):
    """Request session data, including request, response, validators and stat data."""

    success: bool = False
    # in most cases, req_resps only contains one request & response
    # while when 30X redirect occurs, req_resps will contain multiple request & response
    req_resps: List[RequestResponseRecord] = []
    stat: RequestMetrics = RequestMetrics()
    address: AddressData = AddressData()
    validators: Dict = {}
