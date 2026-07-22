class RecipeAssistantError(Exception):
    """Base exception for the V2 application boundary."""


class ConfigurationError(RecipeAssistantError):
    """Raised when an enabled resource lacks required configuration."""


class ResourceError(RecipeAssistantError):
    """Base exception for resource lifecycle failures."""


class ResourceDisabledError(ResourceError):
    """Raised when code requests a resource disabled by configuration."""


class ResourceInitializationError(ResourceError):
    """Raised when a resource factory cannot initialize its resource."""


class ResourceShutdownError(ResourceError):
    """Raised after one or more resources fail to close cleanly."""
