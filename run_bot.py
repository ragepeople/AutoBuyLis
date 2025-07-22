"""Скрипт для запуска бота с автоматическим перезапуском"""
import subprocess
import time
import sys
import os
import logging

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    filename='bot_runner.log'
)
logger = logging.getLogger("BotRunner")

MAX_RESTARTS = 10
RESTART_DELAY = 10  # секунд

def run_bot():
    """Запуск бота с автоматическим перезапуском при ошибках"""
    restarts = 0
    
    while restarts < MAX_RESTARTS:
        logger.info(f"Запуск бота (попытка {restarts + 1}/{MAX_RESTARTS})")
        
        try:
            # Запускаем бота
            process = subprocess.Popen(
                [sys.executable, "main.py"],
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                universal_newlines=True,
                bufsize=1
            )
            
            # Выводим логи в реальном времени
            for line in process.stdout:
                print(line, end='')
                
            # Ждем завершения
            process.wait()
            
            # Проверяем код возврата
            if process.returncode == 0:
                logger.info("Бот завершился успешно")
                break
            else:
                logger.warning(f"Бот завершился с ошибкой (код {process.returncode})")
                restarts += 1
                
        except KeyboardInterrupt:
            logger.info("Получен сигнал остановки (Ctrl+C)")
            if process:
                process.terminate()
            break
        except Exception as e:
            logger.error(f"Ошибка запуска: {e}")
            restarts += 1
        
        # Пауза перед перезапуском
        logger.info(f"Перезапуск через {RESTART_DELAY} секунд...")
        time.sleep(RESTART_DELAY)
    
    if restarts >= MAX_RESTARTS:
        logger.error("Превышено максимальное количество перезапусков")


if __name__ == "__main__":
    run_bot()