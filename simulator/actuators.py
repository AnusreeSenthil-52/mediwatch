"""
Blocks 6a/6b - Actuators.

alarm       -> sounds the alarm and calls the emergency team
nurse_call  -> asks a nurse to check the patient
oxygen      -> opens the oxygen valve
bed_motor   -> raises the head of the bed (eases breathing)
"""

ALL_ACTUATORS = ["alarm", "nurse_call", "oxygen", "bed_motor"]


class BedActuators:
    def __init__(self, patient, attached):
        self.patient = patient
        self.state = {name: False for name in attached}

    def handle(self, actuator, on):
        """Apply a command. Returns True if something changed."""
        if actuator not in self.state or self.state[actuator] == on:
            return False
        self.state[actuator] = on
        p = self.patient
        if actuator == "oxygen":
            p.oxygen = on
        elif actuator == "bed_motor":
            p.bed_raised = on
        elif actuator == "nurse_call" and on:
            p.call_help("nurse")
        elif actuator == "alarm" and on:
            p.call_help("emergency")
        return True
