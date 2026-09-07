"""Domain errors shared by capability modules and the HTTP adapter."""


class ChatAgentsError(Exception):
    """Base class for failures produced by this application."""

    def __init__(
        self,
        message: str = "",
        *,
        upstream_error: object | None = None,
        run_id: str | None = None,
        key_source: str | None = None,
    ) -> None:
        super().__init__(message)
        self.upstream_error = upstream_error
        self.run_id = run_id
        self.key_source = key_source


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
