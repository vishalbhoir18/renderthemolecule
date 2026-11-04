class UserError(Exception):
    """A failure whose message is safe and useful to show to the visitor."""


class QueueFull(Exception):
    pass


class TooManyJobs(Exception):
    pass
