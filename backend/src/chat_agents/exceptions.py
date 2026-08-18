"""Domain errors shared by capability modules and the HTTP adapter."""


class ChatAgentsError(Exception):
    """Base class for failures produced by this application."""


class AuthenticationFailed(ChatAgentsError):
    pass


class ModelNotFound(ChatAgentsError):
    pass


class UpstreamUnavailable(ChatAgentsError):
    pass


class ProtocolError(ChatAgentsError):
    pass


class SessionNotFound(ChatAgentsError):
    pass
