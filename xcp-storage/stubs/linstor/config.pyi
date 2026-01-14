from _typeshed import Incomplete
from linstor.linstorapi import MultiLinstor as MultiLinstor

class Config:
    CONFIG: Incomplete
    @staticmethod
    def read_config(config_file): ...
    @staticmethod
    def get_section(section, config_file_name=None): ...
    @staticmethod
    def get_controllers(section: str = 'global', config_file_name=None, fallback: str = 'linstor://localhost'): ...
