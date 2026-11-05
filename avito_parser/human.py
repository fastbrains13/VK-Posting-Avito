"""Имитация поведения человека (архитектура из ТЗ: random delays, scroll, mouse).

Модуль не содержит знаний о структуре Авито — только «поведенческие» примитивы,
которые вызывает скрейпер.
"""

from __future__ import annotations

import random
import time
from typing import Callable

from selenium.webdriver.remote.webdriver import WebDriver

from .config import BrowserConfig
from .logger import get_logger

logger = get_logger("avito.human")


class HumanBehavior:
    """Набор приёмов, делающих сессию похожей на действия реального пользователя."""

    def __init__(self, config: BrowserConfig | None = None):
        self.config = config or BrowserConfig()
        self._pause_multiplier = 1.0  # растёт при блокировках

    # ------------------------------------------------------------------ #
    # задержки
    # ------------------------------------------------------------------ #
    def pause(self, min_seconds: float | None = None, max_seconds: float | None = None) -> None:
        """Случайная пауза (ТЗ: 2-5 секунд между действиями)."""
        low = (min_seconds if min_seconds is not None else self.config.delay_min) * self._pause_multiplier
        high = (max_seconds if max_seconds is not None else self.config.delay_max) * self._pause_multiplier
        high = max(high, low + 0.2)
        delay = random.uniform(low, high)
        time.sleep(delay)

    def increase_tension(self) -> None:
        """После блокировки увеличиваем все паузы в 1.5 раза (адаптивный троттлинг)."""
        self._pause_multiplier = min(self._pause_multiplier * 1.5, 6.0)
        logger.info("Паузы увеличены в %.1f раз", self._pause_multiplier)

    def relax(self) -> None:
        self._pause_multiplier = 1.0

    # ------------------------------------------------------------------ #
    # прокрутка
    # ------------------------------------------------------------------ #
    def scroll_page(self, driver: WebDriver, steps: int | None = None) -> None:
        """Плавная прокрутка вниз порциями разного размера с «остановками на чтение»."""
        steps = steps or random.randint(4, 7)
        for _ in range(steps):
            delta = random.randint(300, 1000)
            try:
                driver.execute_script(f"window.scrollBy({{top: {delta}, behavior: 'smooth'}});")
            except Exception:
                driver.execute_script(f"window.scrollBy(0, {delta});")
            time.sleep(random.uniform(0.35, 1.1))
            if random.random() < 0.3:  # иногда пользователь «читает»
                time.sleep(random.uniform(1.0, 2.5))
        if random.random() < 0.4:  # и иногда возвращается назад
            driver.execute_script(f"window.scrollBy({{top: -{random.randint(150, 500)}, behavior: 'smooth'}});")
            time.sleep(random.uniform(0.4, 1.0))

    def scroll_into_view(self, driver: WebDriver, element) -> None:
        try:
            driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", element)
        except Exception:
            pass

    # ------------------------------------------------------------------ #
    # мышь
    # ------------------------------------------------------------------ #
    def move_mouse(self, driver: WebDriver, steps: int = 6) -> None:
        """Случайное движение мыши по дуге Безье — ActionChairs без привязки к элементу."""
        from selenium.webdriver.common.action_chains import ActionChains
        from selenium.webdriver.common.actions import interaction

        try:
            actions = ActionChains(driver)
            actions.w3c_actions.pointer_action.move_to_location(
                random.randint(100, 900), random.randint(100, 600)
            )
            actions.w3c_actions.pointer_action.pointer_type(interaction.InteractionType.POINTER)
            for _ in range(steps):
                actions.w3c_actions.pointer_action.move_by(
                    random.randint(-120, 160), random.randint(-90, 110)
                )
                actions.w3c_actions.pointer_action.pause(random.uniform(0.05, 0.25))
            actions.perform()
        except Exception as exc:  # в headless действия мыши иногда не проходят
            logger.debug("Движение мыши пропущено: %s", exc)

    def idle_like_user(self, driver: WebDriver, read_seconds: tuple[float, float] = (1.0, 3.0)) -> None:
        """Немного «почитать» страницу: курсор + пауза."""
        if random.random() < 0.7:
            self.move_mouse(driver)
        time.sleep(random.uniform(*read_seconds))

    # ------------------------------------------------------------------ #
    # ожидание контента
    # ------------------------------------------------------------------ #
    def wait_for(self, driver: WebDriver, condition: Callable[[], bool], timeout: float = 20.0,
                 poll: float = 0.5, settle: float = 1.0) -> bool:
        """Ждать выполнение условия, имитируя терпеливую загрузку контента."""
        deadline = time.time() + timeout
        while time.time() < deadline:
            try:
                if condition():
                    time.sleep(settle)  # даём DOM «догрузиться»
                    return True
            except Exception:
                pass
            time.sleep(poll)
        return False
