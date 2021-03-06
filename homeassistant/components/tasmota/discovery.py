"""Support for MQTT discovery."""
import asyncio
import logging

from hatasmota.const import CONF_RELAY
from hatasmota.discovery import (
    TasmotaDiscovery,
    get_device_config as tasmota_get_device_config,
    get_entities_for_platform as tasmota_get_entities_for_platform,
    get_entity as tasmota_get_entity,
    has_entities_with_platform as tasmota_has_entities_with_platform,
)

from homeassistant.helpers.dispatcher import async_dispatcher_send
from homeassistant.helpers.typing import HomeAssistantType

from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)

SUPPORTED_COMPONENTS = {
    "switch": CONF_RELAY,
}

ALREADY_DISCOVERED = "tasmota_discovered_components"
CONFIG_ENTRY_IS_SETUP = "tasmota_config_entry_is_setup"
DATA_CONFIG_ENTRY_LOCK = "tasmota_config_entry_lock"
TASMOTA_DISCOVERY_DEVICE = "tasmota_discovery_device"
TASMOTA_DISCOVERY_ENTITY_NEW = "tasmota_discovery_entity_new_{}"
TASMOTA_DISCOVERY_ENTITY_UPDATED = "tasmota_discovery_entity_updated_{}_{}_{}"


def clear_discovery_hash(hass, discovery_hash):
    """Clear entry in ALREADY_DISCOVERED list."""
    del hass.data[ALREADY_DISCOVERED][discovery_hash]


def set_discovery_hash(hass, discovery_hash):
    """Set entry in ALREADY_DISCOVERED list."""
    hass.data[ALREADY_DISCOVERED][discovery_hash] = {}


async def async_start(
    hass: HomeAssistantType, discovery_topic, config_entry, tasmota_mqtt
) -> bool:
    """Start MQTT Discovery."""

    async def async_device_discovered(payload, mac):
        """Process the received message."""

        if ALREADY_DISCOVERED not in hass.data:
            hass.data[ALREADY_DISCOVERED] = {}

        _LOGGER.debug("Received discovery data for tasmota device: %s", mac)
        tasmota_device_config = tasmota_get_device_config(payload)
        async_dispatcher_send(
            hass, TASMOTA_DISCOVERY_DEVICE, tasmota_device_config, mac
        )

        async with hass.data[DATA_CONFIG_ENTRY_LOCK]:
            for component, component_key in SUPPORTED_COMPONENTS.items():
                if not tasmota_has_entities_with_platform(payload, component_key):
                    continue
                config_entries_key = f"{component}.tasmota"
                if config_entries_key not in hass.data[CONFIG_ENTRY_IS_SETUP]:
                    await hass.config_entries.async_forward_entry_setup(
                        config_entry, component
                    )
                    hass.data[CONFIG_ENTRY_IS_SETUP].add(config_entries_key)

        for component, component_key in SUPPORTED_COMPONENTS.items():
            tasmota_entities = tasmota_get_entities_for_platform(payload, component_key)
            for (idx, tasmota_entity_config) in enumerate(tasmota_entities):
                discovery_hash = (mac, component, idx)
                if not tasmota_entity_config:
                    # Entity disabled, clean up entity registry
                    entity_registry = (
                        await hass.helpers.entity_registry.async_get_registry()
                    )
                    unique_id = "{}_{}_{}".format(*discovery_hash)
                    entity_id = entity_registry.async_get_entity_id(
                        component, DOMAIN, unique_id
                    )
                    if entity_id:
                        _LOGGER.debug(
                            "Removing entity: %s %s", component, discovery_hash
                        )
                        entity_registry.async_remove(entity_id)
                    continue

                if discovery_hash in hass.data[ALREADY_DISCOVERED]:
                    _LOGGER.debug(
                        "Entity already added, sending update: %s %s",
                        component,
                        discovery_hash,
                    )
                    async_dispatcher_send(
                        hass,
                        TASMOTA_DISCOVERY_ENTITY_UPDATED.format(*discovery_hash),
                        tasmota_entity_config,
                    )
                else:
                    _LOGGER.debug("Adding new entity: %s %s", component, discovery_hash)
                    hass.data[ALREADY_DISCOVERED][discovery_hash] = None

                    tasmota_entity = tasmota_get_entity(
                        tasmota_entity_config, component_key, tasmota_mqtt
                    )

                    async_dispatcher_send(
                        hass,
                        TASMOTA_DISCOVERY_ENTITY_NEW.format(component),
                        tasmota_entity,
                        discovery_hash,
                    )

    hass.data[DATA_CONFIG_ENTRY_LOCK] = asyncio.Lock()
    hass.data[CONFIG_ENTRY_IS_SETUP] = set()

    tasmota_discovery = TasmotaDiscovery(discovery_topic, tasmota_mqtt)
    await tasmota_discovery.start_discovery(async_device_discovered)
