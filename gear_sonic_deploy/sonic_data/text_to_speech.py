import pyttsx3


class TextToSpeech:
    def __init__(self, rate: int = 150, volume: float = 1.0):
        try:
            self.engine = pyttsx3.init(driverName="espeak")
            self.engine.setProperty("rate", rate)
            self.engine.setProperty("volume", volume)
        except Exception as exc:
            print(f"[Text To Speech] Initialization failed: {exc}")
            self.engine = None

    def say(self, message: str):
        if self.engine:
            try:
                self.engine.say(message)
                self.engine.runAndWait()
            except Exception as exc:
                print(f"[Text To Speech] Failed to say message: {exc}")

    def print_and_say(self, message: str, say: bool = True):
        print(message)
        if say and self.engine is not None:
            self.say(message)
