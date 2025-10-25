# Raspberry Pi Container Return System

A simplified container return system for Raspberry Pi that communicates with an STM32 microcontroller via UART. The system handles container returns through three simple sequences: button press, cover insertion, and container insertion with QR validation.

## 🚀 Features

- **3 Simple Sequences**: Button press → Cover insertion → Container insertion
- **Simplified Architecture**: No complex state machines or threading
- **UART Communication**: Direct communication with STM32 microcontroller
- **QR Code Scanning**: Integrated QR scanning via UART messages
- **Database Storage**: SQLite with audit logging

## 🛠 Installation

### 1. Clone the Repository

```bash
git clone https://github.com/Nyxidiom/Paka_raspberry.git
cd Paka_raspberry
```

### 2. Ports set up

#### WINDOWS - Install Null Modem Emulator (com0com)

**Required for hardware simulation testing on Windows.**

1. **Download com0com:**
   - Download from: https://sourceforge.net/projects/com0com/
   - Or search for "com0com null modem emulator"

2. **Install com0com:**
   - Run the installer as administrator
   - Follow the installation wizard

3. **Configure Virtual COM Ports:**
   - Open "Setup for com0com" (installed with com0com)
   - Run as administrator
   - In the com0com terminal, run:

   ```bash
   install PortName=COM7 PortName=COM8
   ```

   - This creates a virtual connection between COM7 and COM8
   - The hardware simulator uses COM7, the main app uses COM8

#### Linux

We will need to install socat to run virtual serial ports:

```bash
sudo apt install socat
```

Then to open the ports:

```bash
socat -d -d pty,raw,echo=0 pty,raw,echo=0
```

This wil have an output like:

```
2025/07/28 15:31:35 Cursor-0.50.5-x86_64.AppImage[591554] N PTY is /dev/pts/9
2025/07/28 15:31:35 Cursor-0.50.5-x86_64.AppImage[591554] N PTY is /dev/pts/12
2025/07/28 15:31:35 Cursor-0.50.5-x86_64.AppImage[591554] N starting data transfer loop with FDs [5,5] and [7,7]
```

Where `/dev/pts/9` and `/dev/pts/12` are the ports we will have to use instead of `COM7` and `COM8`

### 3. Create Virtual Environment

```bash
python3 -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate
```

In linux we will need to use sudo and run it in every terminal that will have to run the code:

```bash
sudo python3 -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate
```

### 4. Install Dependencies

```bash
pip install -r requirements.txt
```

With linux

```bash
sudo pip install -r requirements.txt
```

### 5. Configuration Setup

```bash
# Copy environment template
cp env.template .env

# Edit configuration file
nano .env
```

### 6. Required Environment Variables

Edit `.env` file with your specific configuration:

```bash
# Required settings
RASPBERRY_NAME=device_001
API_KEY=your_global_api_key_here
RASPBERRY_API_KEY=your_device_specific_api_key_here

# Optional settings (defaults provided-we do not use UART port from env for now.)
DATABASE_URL=sqlite:///./container_system.db
UART_PORT=/dev/ttyUSB0
UART_BAUDRATE=9600
DEBUG=false
LOG_LEVEL=INFO
```

## 🧪 Testing Tools

The project includes testing tools to simulate hardware and test the system without physical components.

### Hardware Simulator

The `tools/hardware_sim_com7.py` simulates the STM32 microcontroller and provides a virtual UART interface for testing.

**What it does:**

- Simulates STM32 microcontroller behavior
- Provides virtual COM7 port for UART communication
- Responds to UART commands from the main application
- Simulates sensor states, button presses, and QR scans
- Allows testing of all three sequences without hardware

**How to run:**

```bash
# Start the hardware simulator
python tools/hardware_sim_com7.py

# The simulator will:
# 1. Create a virtual COM7 port
# 2. Listen for UART messages from the main app
# 3. Respond with appropriate ACK messages
# 4. Simulate sensor state changes
# 5. Accept QR code scans via command line

# Direct commands in simulator:
# - Type "button" to send button press
# - Type "cover" to send cover detection
# - Type "container" to send container detection
# - Type "qr CODE123" to send QR scan
# - Use menu options 1-7 for interactive testing
```

### Application Runner

The `run_app_com8.py` script runs the main application configured to communicate with the hardware simulator.

**What it does:**

- Runs the main container return system
- Connects to COM8 (which communicates with the simulator's COM7)
- Processes UART messages and sequences
- Handles QR scanning and container validation
- Provides real-time logging and status updates

**How to run:**

```bash
# In a separate terminal, run the main application
python run_app_com8.py

# The application will:
# 1. Initialize UART communication on COM8
# 2. Start the main application loop
# 3. Process incoming UART messages
# 4. Execute sequences based on events
# 5. Handle QR code scanning and validation
```

### Testing Workflow

1. **Start Hardware Simulator:**

   ```bash
   python tools/hardware_sim_com7.py
   ```

2. **Start Main Application:**

   ```bash
   python run_app_com8.py
   ```

3. **Test Sequences:**
   - **Button Press**: Type `button` in the simulator to trigger SEQ1
   - **Cover Detection**: Type `cover` in the simulator to trigger SEQ2
   - **Container Detection**: Type `container` in the simulator to trigger SEQ3
   - **QR Scanning**: Type `qr CODE123` in the simulator to simulate QR scan
   - **Interactive Menu**: Use numbers 1-7 for menu-driven testing

4. **Monitor Results:**
   - Watch the application logs for sequence execution
   - Check database for container records
   - Verify UART message exchange

### UART Utilities

The `tools/uart_utils.py` provides utility functions for UART communication testing and debugging.

**Features:**

- UART connection testing
- Message sending and receiving
- Port enumeration and validation
- Communication debugging tools

### Troubleshooting

#### com0com Issues

If you encounter problems with the hardware simulator:

1. **Verify com0com Installation:**
   - Open "Setup for com0com" as administrator
   - Check that COM7 and COM8 are listed and connected
   - If not, run: `install PortName=COM7 PortName=COM8`

2. **Port Already in Use:**
   - If COM7 or COM8 are already in use, you can use different ports
   - Update the com0com configuration: `install PortName=COM9 PortName=COM10`
   - Update the hardware simulator to use the new port
   - Update the main application to use the corresponding port

## 📡 UART Communication

### Message Protocol

Frame format: `START_BYTE + TYPE + ID + LENGTH + PAYLOAD`

**Message Types:**

- `0x00` - ACK responses
- `0x01` - Get sensor status
- `0x02` - Sensor state changes (cover/container sensors)
- `0x03` - Restart command
- `0x04` - Actuator control (open/close mechanisms)
- `0x05` - Light control (status indicators)
- `0x06` - Button press events
- `0x07` - Error messages
- `0x08` - QR code scan events

### QR Code Scanning

The system integrates QR code scanning via UART messages:

- **Message Type**: `0x08` - QR scan events from micro
- **Payload**: UTF-8 encoded QR code string
- **Validation**: Basic format validation (6-20 chars, alphanumeric + dash/underscore)
- **Processing**: Simplified container ID extraction and return decision logic

## 🔄 Container Return Sequences

### Three Simple Sequences

#### **SEQ1: Button Press Sequence**

1. User pushes button
2. Micro sends 0x06 (button pressed)
3. Pi sends ACK
4. Pi sends 0x05 msg Cover White light turn ON
5. Micro turns On cover white light
6. Micro sends ACK
7. Pi sends 0x05 msg Container White light turn ON
8. Micro turns On Container white light
9. Micro sends ACK

#### **SEQ2: Cover Detection Sequence**

1. User enters cover
2. Micro sends 0x02 msg cover detected
3. Pi sends ACK
4. Pi sends 0x04 msg actuator Open Cover
5. Micro ACKs, and Opens the cover
6. Micro sends ACK

#### **SEQ3: Container Detection Sequence**

1. User enters container
2. Micro sends 0x02 msg container detected
3. Pi sends ACK
4. Pi checks QR code is valid
5. Pi sends 0x04 msg actuator Open door
6. Micro ACKs, and Opens door
7. Micro sends ACK
8. Pi sends 0x04 actuator move conveyor
9. Micro ACKs, and activates conveyor
10. Micro sends ACK
11. Pi sends 0x05 Container Green light turn ON
12. Micro turns On Container Green light
13. Micro sends ACK

## 🏗 Project Structure

```
raspberry-container-system/
├── src/                      # Main application source code
│   ├── main.py              # Application entry point
│   ├── api/                 # API client and service
│   ├── config/              # Configuration management
│   ├── database/            # Database operations
│   ├── uart/                # UART communication
│   ├── qr/                  # QR code processing
│   └── audit/               # Audit logging
├── logs/                    # Application and audit logs
│   ├── system.log          # Main application logs
│   └── audit.log           # Audit trail logs
├── tools/                   # Testing and utility tools
│   ├── hardware_sim_com7.py # Hardware simulator
│   ├── uart_utils.py        # UART utilities
│   ├── specs.json          # Hardware specifications
│   └── view_database.py     # Database viewer
├── run_app_com8.py          # Application runner
├── env.template             # Environment template
└── requirements.txt         # Python dependencies
```

## 🧪 Testing

### Database Viewing

```bash
# View all tables
python tools/view_database.py

# View specific table
python tools/view_database.py DeviceStatus
```

### Configuration Testing

```bash
# Check current environment variables
python -m src.main --check-config

# Test with debug mode
python -m src.main --debug
```

## 📊 Monitoring and Logs

### Application Logs

```bash
# View real-time logs
tail -f logs/system.log

# View audit logs
tail -f logs/audit.log
```

## 🔧 Maintenance

### Log Rotation

Logs are automatically rotated based on the following settings:

- Maximum file size: 10MB
- Backup count: 5 files
- Format: `{filename}.{timestamp}.gz`
