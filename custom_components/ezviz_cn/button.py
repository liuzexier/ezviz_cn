"""Support for EZVIZ button controls."""

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from pyezvizapi import EzvizClient
from pyezvizapi.constants import SupportExt
from pyezvizapi.exceptions import HTTPError, PyEzvizError

from homeassistant.components.button import ButtonEntity, ButtonEntityDescription
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .coordinator import EzvizConfigEntry, EzvizDataUpdateCoordinator
from .entity import EzvizEntity

PARALLEL_UPDATES = 1


@dataclass(frozen=True, kw_only=True)
class EzvizButtonEntityDescription(ButtonEntityDescription):
    """Describe a EZVIZ Button."""

    method: Callable[[EzvizClient, str, str], Any]
    supported_exts: tuple[str, ...]


PTZ_ANY_CAPABILITIES = (
    str(SupportExt.SupportPtz.value),
    str(SupportExt.SupportPtzManualCtrl.value),
    str(SupportExt.SupportPtzNew.value),
)
PTZ_MODEL_HINTS = ("c6", "c6c", "c6n", "c6w", "c8", "cp1", "h6c")
BUTTON_NAMES = {
    "ptz_up": "云台上移",
    "ptz_down": "云台下移",
    "ptz_left": "云台左移",
    "ptz_right": "云台右移",
}


BUTTON_ENTITIES = (
    EzvizButtonEntityDescription(
        key="ptz_up",
        translation_key="ptz_up",
        method=lambda pyezviz_client, serial, run: pyezviz_client.ptz_control(
            "UP", serial, run
        ),
        supported_exts=(
            *PTZ_ANY_CAPABILITIES,
            str(SupportExt.SupportPtzTopBottom.value),
        ),
    ),
    EzvizButtonEntityDescription(
        key="ptz_down",
        translation_key="ptz_down",
        method=lambda pyezviz_client, serial, run: pyezviz_client.ptz_control(
            "DOWN", serial, run
        ),
        supported_exts=(
            *PTZ_ANY_CAPABILITIES,
            str(SupportExt.SupportPtzTopBottom.value),
        ),
    ),
    EzvizButtonEntityDescription(
        key="ptz_left",
        translation_key="ptz_left",
        method=lambda pyezviz_client, serial, run: pyezviz_client.ptz_control(
            "LEFT", serial, run
        ),
        supported_exts=(
            *PTZ_ANY_CAPABILITIES,
            str(SupportExt.SupportPtzLeftRight.value),
        ),
    ),
    EzvizButtonEntityDescription(
        key="ptz_right",
        translation_key="ptz_right",
        method=lambda pyezviz_client, serial, run: pyezviz_client.ptz_control(
            "RIGHT", serial, run
        ),
        supported_exts=(
            *PTZ_ANY_CAPABILITIES,
            str(SupportExt.SupportPtzLeftRight.value),
        ),
    ),
)


def _is_capability_enabled(value: Any) -> bool:
    """Return whether a supportExt value means enabled."""
    return str(value).lower() in {"1", "true", "yes"}


def _supports_button(
    support_ext: dict[str, Any] | None, capability_ids: tuple[str, ...]
) -> bool:
    """Return whether any capability id required by a PTZ button is enabled."""
    if not isinstance(support_ext, dict):
        return False

    return any(
        _is_capability_enabled(support_ext.get(capability))
        for capability in capability_ids
    )


def _looks_like_ptz_camera(camera_data: dict[str, Any]) -> bool:
    """Return whether model/name hints indicate an EZVIZ pan-tilt camera."""
    values = (
        camera_data.get("name"),
        camera_data.get("device_sub_category"),
        camera_data.get("device_type"),
        camera_data.get("device_model"),
        camera_data.get("model"),
    )
    camera_text = " ".join(str(value).lower() for value in values if value)
    return any(hint in camera_text for hint in PTZ_MODEL_HINTS)


def _supports_ptz_button(
    camera_data: dict[str, Any], capability_ids: tuple[str, ...]
) -> bool:
    """Return whether a camera should expose a PTZ button."""
    return _looks_like_ptz_camera(camera_data) or _supports_button(
        camera_data.get("supportExt"), capability_ids
    )


async def async_setup_entry(
    hass: HomeAssistant,
    entry: EzvizConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up EZVIZ button based on a config entry."""
    coordinator = entry.runtime_data

    # Add button entities if supportExt indicates PTZ capability.

    async_add_entities(
        EzvizButtonEntity(coordinator, camera, entity_description)
        for camera in coordinator.data
        for entity_description in BUTTON_ENTITIES
        if _supports_ptz_button(
            coordinator.data[camera],
            entity_description.supported_exts,
        )
    )


class EzvizButtonEntity(EzvizEntity, ButtonEntity):
    """Representation of a EZVIZ button entity."""

    entity_description: EzvizButtonEntityDescription

    def __init__(
        self,
        coordinator: EzvizDataUpdateCoordinator,
        serial: str,
        description: EzvizButtonEntityDescription,
    ) -> None:
        """Initialize the button."""
        super().__init__(coordinator, serial)
        self._attr_unique_id = f"{serial}_{description.key}"
        self._attr_name = BUTTON_NAMES.get(description.key, description.key)
        self.entity_description = description

    def press(self) -> None:
        """Execute the button action."""
        try:
            self.entity_description.method(
                self.coordinator.ezviz_client, self._serial, "START"
            )
            self.entity_description.method(
                self.coordinator.ezviz_client, self._serial, "STOP"
            )
        except (HTTPError, PyEzvizError) as err:
            raise HomeAssistantError(
                f"Cannot perform PTZ action on {self.name}"
            ) from err
