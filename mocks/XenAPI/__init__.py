class Failure(Exception):
    def __init__(self, details):
        self.details = details

def xapi_local():
    # Mock stub
    pass

class Session(object):
    def __getattr__(self, name):
        pass
