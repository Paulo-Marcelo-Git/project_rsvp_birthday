-- backend/init.sql

SET NAMES utf8mb4;

CREATE TABLE IF NOT EXISTS invitees (
  id INT AUTO_INCREMENT PRIMARY KEY,
  name VARCHAR(255) NOT NULL,
  phone VARCHAR(20),
  email VARCHAR(255),
  token VARCHAR(64) UNIQUE NOT NULL,
  response ENUM('yes', 'no') DEFAULT NULL,
  response_date DATETIME DEFAULT NULL,
  custom_message TEXT,
  diaper_size VARCHAR(100),
  gift VARCHAR(255),
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
  ('question_text','Texto para convite'),
  ('yes_text','Botão Sim'),
  ('no_text','Botão Não'),
  ('post_yes_text','Texto Botão Sim'),
  ('post_no_text','Texto Botão Não');

-- Índices para performance (busca/ordenação)
CREATE INDEX idx_invitees_name ON invitees (name);
CREATE INDEX idx_invitees_email ON invitees (email);
CREATE INDEX idx_invitees_response_date ON invitees (response_date);
