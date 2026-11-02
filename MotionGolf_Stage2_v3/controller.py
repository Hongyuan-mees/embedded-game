import serial
import serial.tools.list_ports


class STM32SerialController:
    def __init__(self):
        self.serial_port = None

        self.roll = 0.0
        self.pitch = 0.0
        self.jump = False

        self.connected = False
        self.port_name = None

        self.roll_offset = 0.0
        self.pitch_offset = 0.0

    @staticmethod
    def get_available_ports():
        ports = []

        for port in serial.tools.list_ports.comports():
            ports.append({
                "device": port.device,
                "description": port.description
            })

        return ports

    def connect(self, port, baudrate=115200):
        self.disconnect()

        try:
            self.serial_port = serial.Serial(
                port=port,
                baudrate=baudrate,
                timeout=0
            )

            self.connected = True
            self.port_name = port

            print(f"STM32 connected: {port}")
            return True

        except serial.SerialException as error:
            print(f"STM32 connection failed: {error}")

            self.serial_port = None
            self.connected = False
            self.port_name = None

            return False

    def disconnect(self):
        if self.serial_port is not None:
            try:
                if self.serial_port.is_open:
                    self.serial_port.close()
            except serial.SerialException:
                pass

        self.serial_port = None
        self.connected = False
        self.port_name = None

        self.roll = 0.0
        self.pitch = 0.0
        self.jump = False

    def calibrate(self):
        self.roll_offset += self.roll
        self.pitch_offset += self.pitch

        self.roll = 0.0
        self.pitch = 0.0

        print("Controller calibrated.")

    def parse_packet(self, line):
        try:
            parts = line.strip().split(",")

            data = {}

            for part in parts:
                key, value = part.split(":", 1)
                data[key.strip().upper()] = value.strip()

            raw_roll = float(data["ROLL"])
            raw_pitch = float(data["PITCH"])
            jump_value = int(data["JUMP"])

            self.roll = raw_roll - self.roll_offset
            self.pitch = raw_pitch - self.pitch_offset
            self.jump = jump_value == 1

            return True

        except (ValueError, KeyError):
            return False

    def update(self):
        self.jump = False

        if not self.connected:
            return

        if self.serial_port is None:
            return

        try:
            # Read every complete packet currently waiting.
            # Keep the newest valid packet.
            while self.serial_port.in_waiting > 0:
                raw_line = self.serial_port.readline()

                if not raw_line:
                    break

                line = raw_line.decode(
                    "utf-8",
                    errors="ignore"
                ).strip()

                if line:
                    self.parse_packet(line)

        except serial.SerialException as error:
            print(f"Serial connection lost: {error}")
            self.disconnect()


if __name__ == "__main__":
    print("Available serial ports:")

    ports = STM32SerialController.get_available_ports()

    if not ports:
        print("No serial ports found.")
    else:
        for port in ports:
            print(
                port["device"],
                "-",
                port["description"]
            )

    print()
    print("Parser test:")

    controller = STM32SerialController()

    test_packet = "ROLL:-12.3,PITCH:4.5,JUMP:1"

    if controller.parse_packet(test_packet):
        print("ROLL =", controller.roll)
        print("PITCH =", controller.pitch)
        print("JUMP =", controller.jump)
    else:
        print("Packet parsing failed.")