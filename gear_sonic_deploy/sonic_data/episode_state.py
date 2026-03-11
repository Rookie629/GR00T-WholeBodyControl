class EpisodeState:
    """Episode state controller for data collection."""

    def __init__(self):
        self.RECORDING = "recording"
        self.IDLE = "idle"
        self.NEED_TO_SAVE = "need_to_save"
        self.state = self.IDLE

    def change_state(self):
        if self.state == self.IDLE:
            self.state = self.RECORDING
        elif self.state == self.RECORDING:
            self.state = self.NEED_TO_SAVE
        elif self.state == self.NEED_TO_SAVE:
            self.state = self.IDLE

    def reset_state(self):
        self.state = self.IDLE

    def get_state(self):
        return self.state
