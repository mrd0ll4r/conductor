#!/usr/bin/env python
import threading

import pika
import json
import requests

AMQP_HOST = "192.168.88.30"
EXCHANGE_NAME = "shack.input"
KALEIDOSCOPE_BASE = "http://192.168.88.30:3545"
API_V1_PREFIX = "/api/v1"
DEBUG = False
VERBOSE = True

# Button aliases.
ALIAS_BUTTON_FRONT_DOOR_LEFT = "button-front-door-left"
ALIAS_BUTTON_FRONT_DOOR_RIGHT = "button-front-door-right"
ALIAS_BUTTON_GLASS_DOOR_LEFT = "button-glassdoor-left"
ALIAS_BUTTON_GLASS_DOOR_RIGHT = "button-glassdoor-right"
ALIAS_BUTTON_BEDROOM_LEFT = "button-bedroom-left"
ALIAS_BUTTON_BEDROOM_RIGHT = "button-bedroom-right"
ALIAS_BUTTON_KITCHEN_LEFT = "button-kitchen-left"
ALIAS_BUTTON_KITCHEN_RIGHT = "button-kitchen-right"

# Fixture names.
FIXTURE_KITCHEN_RGBW = "kitchen_rgbw"
FIXTURE_KITCHEN_SPOTS = "kitchen_spots"
FIXTURE_KLO_RGBW = "klo_rgbw"
FIXTURE_SPOIDER = "spoider"
FIXTURE_FRONT_DOOR_LIGHT = "front_door"
FIXTURE_BLACKLIGHT = "blacklight"
FIXTURE_BEDROOM_LIGHT = "bedroom_light"
FIXTURE_RED_GREEN_PARTY_LIGHT = "red_green_party_light"
FIXTURE_PUTZLICHT_OUTSIDE = "putzlicht"
FIXTURE_LICHTERKETTEN = "lichterketten"

# Program names.
PROGRAM_BUILTIN_ON = "ON"
PROGRAM_BUILTIN_OFF = "OFF"
PROGRAM_BUILTIN_MANUAL = "MANUAL"
PROGRAM_BUILTIN_EXTERNAL = "EXTERNAL"
PROGRAM_NOISE = "noise"
PROGRAM_STROBO = "strobo"
PROGRAM_PARTY = "party"

# Event types.
EVENT_TYPE_BUTTON_DOWN = "Down"
EVENT_TYPE_BUTTON_UP = "Up"
EVENT_TYPE_BUTTON_CLICKED = "Clicked"
EVENT_TYPE_BUTTON_LONG_PRESS = "LongPress"

# Global enable/disable behavior.
BASIC_LIGHT_OFF_STATE = {
    FIXTURE_BLACKLIGHT: PROGRAM_BUILTIN_OFF,
    FIXTURE_SPOIDER: PROGRAM_BUILTIN_OFF,
    FIXTURE_KITCHEN_RGBW: PROGRAM_BUILTIN_OFF,
    FIXTURE_KITCHEN_SPOTS: PROGRAM_BUILTIN_OFF,
    FIXTURE_KLO_RGBW: PROGRAM_BUILTIN_OFF,
    FIXTURE_RED_GREEN_PARTY_LIGHT: PROGRAM_BUILTIN_OFF,
    FIXTURE_BEDROOM_LIGHT: PROGRAM_BUILTIN_OFF,
    FIXTURE_LICHTERKETTEN: PROGRAM_BUILTIN_OFF,
}
BASIC_LIGHT_ON_STATE = {
    FIXTURE_KITCHEN_RGBW: {
        "program": PROGRAM_NOISE,
        "parameters": {
            "brightness": "day"
        }
    },
    FIXTURE_KITCHEN_SPOTS: {
        "program": PROGRAM_BUILTIN_ON,
    },
    FIXTURE_KLO_RGBW: {
        "program": PROGRAM_NOISE,
        "parameters": {
            "brightness": "day"
        }
    },
    FIXTURE_SPOIDER: {
        "program": "bright"
    },
    FIXTURE_BEDROOM_LIGHT: {
        "program": PROGRAM_BUILTIN_ON
    },
    FIXTURE_LICHTERKETTEN: {
        "program": PROGRAM_BUILTIN_ON,
    }
}

# After how many seconds should the outdoor light turn off?
FRONT_DOOR_TURN_OFF_DURATION_SECONDS = 30 * 60

kaleidoscope_client: requests.Session = None

basic_light_on = False
front_door_turn_off_timer: threading.Timer = None


def is_simple_click(event):
    if event["type"] != EVENT_TYPE_BUTTON_CLICKED:
        return False
    duration_secs = event["duration"]["secs"]
    return duration_secs == 0


def is_button_down(event):
    return event["type"] == EVENT_TYPE_BUTTON_DOWN


def is_long_press(event, seconds):
    if event["type"] != EVENT_TYPE_BUTTON_LONG_PRESS:
        return False
    duration_secs = event["seconds"]
    return duration_secs == seconds


def handle_front_door_buttons(alias, event):
    global basic_light_on
    global front_door_turn_off_timer

    if alias == ALIAS_BUTTON_FRONT_DOOR_LEFT:
        if is_button_down(event):
            if not kaleidoscope_fixture_is_off(FIXTURE_KLO_RGBW):
                kaleidoscope_set_program(FIXTURE_KLO_RGBW,
                                         PROGRAM_BUILTIN_OFF)
            else:
                kaleidoscope_set_discrete_parameter(FIXTURE_KLO_RGBW,
                                                    PROGRAM_NOISE,
                                                    "brightness",
                                                    "night")
                kaleidoscope_set_program(FIXTURE_KLO_RGBW,
                                         PROGRAM_NOISE)
        elif is_long_press(event, 1):
            kaleidoscope_set_discrete_parameter(FIXTURE_KLO_RGBW,
                                                PROGRAM_NOISE,
                                                "brightness",
                                                "day")
            kaleidoscope_set_program(FIXTURE_KLO_RGBW,
                                     PROGRAM_NOISE)

    elif alias == ALIAS_BUTTON_FRONT_DOOR_RIGHT:
        if is_button_down(event):
            kaleidoscope_cycle_program(FIXTURE_FRONT_DOOR_LIGHT)
            if not kaleidoscope_fixture_is_off(FIXTURE_FRONT_DOOR_LIGHT):
                # If we turned it on, remember to turn it off at some point.
                if VERBOSE:
                    print("Setting front door turn-off timer")
                front_door_turn_off_timer = threading.Timer(
                    FRONT_DOOR_TURN_OFF_DURATION_SECONDS,
                    kaleidoscope_set_program,
                    args=[
                        FIXTURE_FRONT_DOOR_LIGHT,
                        PROGRAM_BUILTIN_OFF])
                front_door_turn_off_timer.start()
            else:
                # If we turned it off, cancel the timer
                if front_door_turn_off_timer is not None:
                    if VERBOSE:
                        print("Canceling front door turn-off timer")
                    front_door_turn_off_timer.cancel()
        elif is_long_press(event, 1):
            if basic_light_on:
                for fixture in BASIC_LIGHT_OFF_STATE:
                    program = BASIC_LIGHT_OFF_STATE[fixture]
                    kaleidoscope_set_program(fixture, program)
                basic_light_on = False
            else:
                for fixture in BASIC_LIGHT_ON_STATE:
                    program = BASIC_LIGHT_ON_STATE[fixture]["program"]
                    if "parameters" in BASIC_LIGHT_ON_STATE[fixture]:
                        parameters = BASIC_LIGHT_ON_STATE[fixture][
                            "parameters"]
                        for param in parameters:
                            level = parameters[param]
                            kaleidoscope_set_discrete_parameter(fixture,
                                                                program, param,
                                                                level)
                    kaleidoscope_set_program(fixture, program)
                basic_light_on = True


def handle_kitchen_buttons(alias, event):
    if alias == ALIAS_BUTTON_KITCHEN_LEFT:
        if is_button_down(event):
            if not kaleidoscope_fixture_is_off(FIXTURE_KITCHEN_RGBW):
                kaleidoscope_set_program(FIXTURE_KITCHEN_RGBW,
                                         PROGRAM_BUILTIN_OFF)
                kaleidoscope_set_program(FIXTURE_KITCHEN_SPOTS,
                                         PROGRAM_BUILTIN_OFF)
            else:
                kaleidoscope_set_discrete_parameter(FIXTURE_KITCHEN_RGBW,
                                                    PROGRAM_NOISE,
                                                    "brightness",
                                                    "night")
                kaleidoscope_set_program(FIXTURE_KITCHEN_RGBW,
                                         PROGRAM_NOISE)
                kaleidoscope_set_program(FIXTURE_KITCHEN_SPOTS,
                                         PROGRAM_BUILTIN_ON)
        elif is_long_press(event, 1):
            kaleidoscope_set_discrete_parameter(FIXTURE_KITCHEN_RGBW,
                                                PROGRAM_NOISE,
                                                "brightness",
                                                "day")
            kaleidoscope_set_program(FIXTURE_KITCHEN_RGBW,
                                     PROGRAM_NOISE)
            kaleidoscope_set_program(FIXTURE_KITCHEN_SPOTS,
                                     PROGRAM_BUILTIN_ON)
    if alias == ALIAS_BUTTON_KITCHEN_RIGHT:
        if is_button_down(event):
            blacklight_on = not kaleidoscope_fixture_is_off(FIXTURE_BLACKLIGHT)
            red_green_on = not kaleidoscope_fixture_is_off(
                FIXTURE_RED_GREEN_PARTY_LIGHT)
            if blacklight_on and red_green_on:
                kaleidoscope_set_program(FIXTURE_BLACKLIGHT,
                                         PROGRAM_BUILTIN_OFF)
                kaleidoscope_set_program(FIXTURE_RED_GREEN_PARTY_LIGHT,
                                         PROGRAM_BUILTIN_OFF)
            elif blacklight_on and not red_green_on:
                kaleidoscope_set_program(FIXTURE_RED_GREEN_PARTY_LIGHT,
                                         PROGRAM_BUILTIN_ON)
            elif not blacklight_on and red_green_on:
                kaleidoscope_set_program(FIXTURE_BLACKLIGHT,
                                         PROGRAM_BUILTIN_ON)
                kaleidoscope_set_program(FIXTURE_RED_GREEN_PARTY_LIGHT,
                                         PROGRAM_BUILTIN_OFF)
            else:
                kaleidoscope_set_program(FIXTURE_RED_GREEN_PARTY_LIGHT,
                                         PROGRAM_BUILTIN_ON)


def handle_bedroom_buttons(alias, event):
    if alias == ALIAS_BUTTON_BEDROOM_LEFT:
        if is_button_down(event):
            kaleidoscope_cycle_program(FIXTURE_BEDROOM_LIGHT)
    elif alias == ALIAS_BUTTON_BEDROOM_RIGHT:
        if is_button_down(event):
            kaleidoscope_cycle_program(FIXTURE_PUTZLICHT_OUTSIDE)


def handle_glass_door_buttons(alias, event):
    if alias == ALIAS_BUTTON_GLASS_DOOR_LEFT:
        if is_button_down(event):
            if not kaleidoscope_fixture_is_off(FIXTURE_LICHTERKETTEN):
                kaleidoscope_set_program(FIXTURE_LICHTERKETTEN,
                                         PROGRAM_BUILTIN_OFF)
            else:
                kaleidoscope_set_program(FIXTURE_LICHTERKETTEN,
                                         PROGRAM_PARTY)
        elif is_long_press(event, 1):
            kaleidoscope_set_program(FIXTURE_LICHTERKETTEN,
                                     PROGRAM_BUILTIN_ON)
    elif alias == ALIAS_BUTTON_GLASS_DOOR_RIGHT:
        if is_button_down(event):
            kaleidoscope_cycle_program(FIXTURE_SPOIDER)


def handle_button_event(alias, event):
    if DEBUG:
        print(" [X] {}: {}".format(alias, event))

    if alias == ALIAS_BUTTON_KITCHEN_LEFT or alias == ALIAS_BUTTON_KITCHEN_RIGHT:
        handle_kitchen_buttons(alias, event)
    elif alias == ALIAS_BUTTON_FRONT_DOOR_LEFT or alias == ALIAS_BUTTON_FRONT_DOOR_RIGHT:
        handle_front_door_buttons(alias, event)
    elif alias == ALIAS_BUTTON_BEDROOM_LEFT or alias == ALIAS_BUTTON_BEDROOM_RIGHT:
        handle_bedroom_buttons(alias, event)
    elif alias == ALIAS_BUTTON_GLASS_DOOR_LEFT or alias == ALIAS_BUTTON_GLASS_DOOR_RIGHT:
        handle_glass_door_buttons(alias, event)


def kaleidoscope_set_program(fixture, program):
    if VERBOSE:
        print("attempting to set program {} for fixture {}".format(program,
                                                                   fixture))

    resp = kaleidoscope_client.post(
        KALEIDOSCOPE_BASE + API_V1_PREFIX + "/fixtures/" + fixture + "/set_active_program",
        program)

    if resp.status_code != 200:
        print("could not set program {} on fixture {}".format(program, fixture))


def kaleidoscope_cycle_program(fixture):
    if VERBOSE:
        print("attempting to cycle program for fixture {}".format(fixture))

    resp = kaleidoscope_client.post(
        KALEIDOSCOPE_BASE + API_V1_PREFIX + "/fixtures/" + fixture + "/cycle_active_program",
    )

    if resp.status_code != 200:
        print("could not cycle program on fixture {}".format(fixture))

    return resp.text


def kaleidoscope_cycle_discrete_parameter(fixture, program, parameter_name):
    if VERBOSE:
        print("attempting to cycle parameter {} for program {} for fixture {}"
              .format(parameter_name, program, fixture))

    resp = kaleidoscope_client.post(
        KALEIDOSCOPE_BASE + API_V1_PREFIX + "/fixtures/" + fixture + "/programs/" + program +
        "/parameters/" + parameter_name + "/cycle",
    )

    if resp.status_code != 200:
        print(
            "could not cycle parameter {} for program {} on fixture {}".format(
                parameter_name, program,
                fixture))

    return resp.text


def kaleidoscope_set_discrete_parameter(fixture,
                                        program,
                                        parameter_name,
                                        parameter_level):
    if VERBOSE:
        print(
            "attempting to set parameter {} to {} for program {} for fixture {}"
            .format(parameter_name, parameter_level, program, fixture))

    set_req = {
        "type": "discrete",
        "level": parameter_level,
    }

    resp = kaleidoscope_client.post(
        KALEIDOSCOPE_BASE + API_V1_PREFIX + "/fixtures/" + fixture + "/programs/" + program + "/parameters/" + parameter_name,
        json=set_req)

    if resp.status_code != 200:
        print(
            "could not set parameter {} to {} for program {} on fixture {}".format(
                parameter_name, parameter_level, program,
                fixture))


def kaleidoscope_fixture_is_off(fixture):
    if VERBOSE:
        print(
            "checking running program of fixture {}"
            .format(fixture))

    resp = kaleidoscope_client.get(
        KALEIDOSCOPE_BASE + API_V1_PREFIX + "/fixtures/" + fixture)

    if resp.status_code != 200:
        print("could not get status of fixture {}".format(fixture))

    resp_decoded = json.loads(resp.text)
    return resp_decoded["selected_program"] == PROGRAM_BUILTIN_OFF


def amqp_message_received(ch, method, properties, body):
    if DEBUG:
        print(f" [x] {method.routing_key}:{body}")

    decoded_body = json.loads(body)
    alias = decoded_body["alias"]
    event = decoded_body["event"]["inner"]

    if "Ok" not in event:
        return
    inner_event = event["Ok"]

    if "Button" not in inner_event:
        return
    button_event = inner_event["Button"]

    handle_button_event(alias, button_event)


def connect_kaleidoscope():
    s = requests.Session()
    r = s.get(KALEIDOSCOPE_BASE)

    if r.status_code != 200:
        raise "Request failed"

    return s


def connect_amqp():
    connection = pika.BlockingConnection(
        pika.ConnectionParameters(host=AMQP_HOST))
    channel = connection.channel()
    channel.basic_qos(prefetch_count=10)
    channel.exchange_declare(exchange=EXCHANGE_NAME, exchange_type='topic')
    result = channel.queue_declare('', exclusive=True, durable=False)
    queue_name = result.method.queue
    channel.queue_bind(exchange=EXCHANGE_NAME, queue=queue_name,
                       routing_key="type.binary.alias.*")
    channel.basic_consume(
        queue=queue_name, on_message_callback=amqp_message_received,
        auto_ack=True)
    return channel


def main():
    global kaleidoscope_client

    print("Connecting to Kaleidoscope at {}...".format(KALEIDOSCOPE_BASE))
    kaleidoscope_client = connect_kaleidoscope()

    print("Connecting to AMQP broker at {}...".format(AMQP_HOST))
    channel = connect_amqp()

    print("Listening for events (peacefully). To exit, press Ctrl+C")

    channel.start_consuming()


if __name__ == '__main__':
    main()
