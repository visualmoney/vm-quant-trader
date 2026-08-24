from threading import Thread


class BaseStrategyExcutor(Thread):
    """Base class for strategy executors."""
    
    def __init__(self):
        super().__init__()
        self.daemon = True


