-- backend/init.sql

SET NAMES utf8mb4;
-- garante que o SQL seja interpretado como UTF-8

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
) ENGINE=InnoDB
  DEFAULT CHARSET=utf8mb4
  COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS settings (
  `key` VARCHAR(50) PRIMARY KEY,
  `value` TEXT NOT NULL
) ENGINE=InnoDB
  DEFAULT CHARSET=utf8mb4
  COLLATE=utf8mb4_unicode_ci;

INSERT IGNORE INTO settings (`key`,`value`) VALUES
  ('question_text','Você confirma a sua presença no aniversário do Antony?'),
  ('yes_text','Sim'),
  ('no_text','Não'),
  ('post_yes_text','Sim'),
  ('post_no_text','Não');
