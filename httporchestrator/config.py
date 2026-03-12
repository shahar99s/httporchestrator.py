import copy
import inspect

from httporchestrator.models import ConfigData, VariablesMapping


class Config(object):
    def __init__(self, name: str) -> None:
        caller_frame = inspect.stack()[1]
        self.__name: str = name
        self.__base_url: str = ""
        self.__variables: VariablesMapping = {}
        self.__config = ConfigData(name=name, path=caller_frame.filename)
        self.__add_request_id = True

    @property
    def name(self) -> str:
        return self.__config.name

    @property
    def path(self) -> str:
        return self.__config.path

    def variables(self, **variables) -> "Config":
        self.__variables.update(variables)
        return self

    def base_url(self, base_url: str) -> "Config":
        self.__base_url = base_url
        return self

    def verify(self, verify: bool) -> "Config":
        self.__config.verify = verify
        return self

    def add_request_id(self, add_request_id: bool) -> "Config":
        self.__config.add_request_id = add_request_id
        return self

    def log_details(self, log_details: bool) -> "Config":
        self.__config.log_details = log_details
        return self

    def export(self, *export_var_name: str) -> "Config":
        self.__config.export.extend(export_var_name)
        self.__config.export = list(set(self.__config.export))
        return self

    def struct(self) -> ConfigData:
        self._initialize()
        return self.__config

    def _initialize(self) -> None:
        self.__config.name = self.__name
        self.__config.base_url = self.__base_url
        self.__config.variables = copy.copy(self.__variables)
