# Device Booking Bot Documentation

---

## **Overview**
The Device Booking Bot is a Telegram bot designed to streamline the management of devices in an organization. It allows users to:
- Book and manage devices.
- View booked devices.
- Administrators can manage users and devices.
- Maintain logs of actions such as bookings and releases.

---

## **Features**

### **For Users**
1. **Device Booking**:
   - Book available devices by type.
   - View the list of all devices and their statuses.
   - View your currently booked devices.

2. **User Registration**:
   - Register using the `/register` command if the registration mode is enabled.
   - Wait for administrator approval for activation.

---

### **For Administrators**
1. **Manage Devices**:
   - Add new devices.
   - Edit or delete existing devices.
   - Import devices from a CSV file.
   - View booking history of each device.

2. **Manage Users**:
   - Approve or reject registration requests.
   - View the list of all users along with their roles.
   - Add new users manually.
   - Edit user details (name, username, role).
   - Delete users.

3. **Registration Mode**:
   - Enable or disable user registration directly from the admin panel.

4. **Booking Logs**:
   - Maintain a log of all device bookings and returns, with user details.

---

## **Commands**

### **General Commands**
- `/start` — Open the main menu.
- `/help` — Show help information.
- `/register` — Submit a registration request (if enabled).

### **Administrator Commands**
- `/toggle_registration` — Enable or disable the registration mode.

---

## **How to Use**

### **User Workflow**
1. **Registering**:
   - Send `/register` to submit a registration request.
   - Wait for admin approval.

2. **Booking a Device**:
   - Open the main menu with `/start`.
   - Choose "Book Device" and select the device type.
   - Pick an available device from the list.

3. **Viewing Devices**:
   - "My Devices" shows your booked devices.
   - "All Booked Devices" displays all booked devices (with names of users who booked them).

---

### **Administrator Workflow**
1. **Managing Users**:
   - Navigate to "Manage Users" in the admin panel.
   - Approve or reject registration requests.
   - View the list of all users with roles.
   - Add, edit, or delete users.

2. **Managing Devices**:
   - Navigate to "Manage Devices" in the admin panel.
   - Add new devices or import from a CSV file (format: `SN, Name, Type`).
   - Edit or delete existing devices.
   - View booking history for each device.

3. **Enabling/Disabling Registration**:
   - Use the "Toggle Registration" button in the "Manage Users" menu.

4. **Logs**:
   - Booking and return logs are saved in `device_logs.txt`.

---

## **JSON File Descriptions**

### **1. config.json**
The `config.json` file contains configuration data for the bot.

| **Field**    | **Type**   | **Description**                               |
|--------------|------------|-----------------------------------------------|
| `bot_token`  | String     | Telegram bot token obtained from BotFather.  |

**Example**:
```json
{
  "bot_token": "YOUR_TELEGRAM_BOT_TOKEN"
}
