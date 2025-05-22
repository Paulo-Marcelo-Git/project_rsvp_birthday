-- backend\init.sql
CREATE TABLE IF NOT EXISTS invitees (
  id INT AUTO_INCREMENT PRIMARY KEY,
  name VARCHAR(255) NOT NULL,
  phone VARCHAR(20),
  email VARCHAR(255),
  token VARCHAR(64) UNIQUE NOT NULL,
  response ENUM('yes', 'no') DEFAULT NULL,
  response_date DATETIME DEFAULT NULL,
  custom_message TEXT,
  created_at DATETIME DEFAULT CURRENT_TIMESTAMP
);