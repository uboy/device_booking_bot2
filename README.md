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

2. **Scanning QR Codes and Serial Numbers**:
   - Scan QR codes or barcodes using the built-in Telegram scanner.
   - Take a photo of a device with a printed serial number - the bot will automatically recognize it using OCR.
   - Manually enter the serial number (full or partial).
   - The bot will find the device and offer actions (book, release, or transfer).

2. **User Registration**:
   - Register using the `/register` command if the registration mode is enabled.
   - Wait for administrator approval for activation.

---

### **For Administrators**
1. **Manage Devices**:
   - Add new devices.
   - Edit or delete existing devices.
   - Import devices from a CSV/XLSX file.
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

## **Installation**

### **Dependencies**

Install required packages:

```bash
pip install -r requirements.txt
```

**Note:** For OCR functionality (recognizing serial numbers from photos), you need to install `easyocr`:

```bash
pip install easyocr
```

The first time you use OCR, it will download language models (this may take a few minutes).

### Docker

**Bot контейнер**
1. Подготовьте директорию `data` рядом с `docker-compose.yml`:
   - скопируйте `config.json_template` в `data/config.json` и пропишите токен/админов;
   - при необходимости скопируйте `devices.json_template` и `users.json_template` в `data/`.
2. Соберите и поднимите контейнер:
   ```bash
   docker-compose up -d --build
   ```
   Данные и логи будут храниться в `./data` (переменная `DATA_DIR=/app/data` прокинута в контейнер).

**WebApp сканер (отдельный сервер)**
1. Настройте домен и откройте порты 80/443 на хосте. Создайте `.env` рядом с `docker-compose.webapp.yml`:
   ```
   DOMAIN=your.domain.example
   LE_EMAIL=you@example.com
   ```
2. Соберите и запустите webapp:
   ```bash
   docker-compose -f docker-compose.webapp.yml up -d --build
   ```
   Сертификаты, ключи и логи лежат на хосте в `./certbot/` (монтируются в контейнер).
3. Получить/обновить сертификат (порт 80 должен быть доступен наружу):
   ```bash
   docker-compose -f docker-compose.webapp.yml run --rm certbot
   docker-compose -f docker-compose.webapp.yml restart webapp_scanner
   ```
   Nginx автоматически переключится на HTTPS, когда появятся файлы в `/etc/letsencrypt/live/$DOMAIN`.
4. Укажите полный HTTPS-URL в `config.json` → `webapp_url`.
5. WebApp доступен по `/webapp_scanner.html` (а также как `index.html`).

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
   - Add new devices or import from a CSV/XLSX file (format: `SN, Name, Type[, GroupId]`; `GroupId` optional).
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
