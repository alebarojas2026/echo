# Radio Sight Architecture

Radio Sight keeps sensing, learned decisions, and explanation on the Arduino UNO Q. The Raspberry Pi supplies the private sensing hotspot, one radio receiver, and the display; it runs no model.

```mermaid
flowchart LR
    subgraph PI["Raspberry Pi"]
        PI_RADIO["Pi radio node<br/>Wi-Fi and Bluetooth readings"]
        SCREEN["Browser screen<br/>Pi-driven display"]
    end

    subgraph UNO["Arduino UNO Q — Dragonwing CPU"]
        WIFI["Wi-Fi RSSI reader"]
        BLE["Bluetooth HCI reader"]
        TEACHER["Camera teacher<br/>setup labels only"]
        CAMWATCH["Camera watcher<br/>on / off / stalled"]
        BUS["Message bus<br/>UDP 0.0.0.0:5600"]

        subgraph BRAIN["Brain"]
            FEATURES["Windowing and features"]
            HEALTH["Link health"]
            MODEL["Person / object / zone / motion model"]
            XRAY["Radio X-ray"]
            CHECKIN["Check-in rule"]
            ALERT["No-movement alert"]
            ADVISOR["Router advisor"]
        end

        NARRATOR["Narrator"]
        SERVE["Web server<br/>http://192.168.77.2:8080"]
        BRIDGE["Host Bridge<br/>arduino package"]
        LED["UNO Q microcontroller<br/>LED grid"]
    end

    PI_RADIO -->|"rssi over Ethernet<br/>192.168.77.2:5600"| BUS
    WIFI -->|"rssi<br/>127.0.0.1:5600"| BUS
    BLE -->|"rssi<br/>127.0.0.1:5600"| BUS
    TEACHER -->|"label<br/>msgpack-rpc-router:5600"| BUS
    CAMWATCH -->|"cam<br/>127.0.0.1:5600"| BUS

    BUS -->|"forwarded UDP<br/>127.0.0.1:5601"| FEATURES
    FEATURES --> HEALTH
    HEALTH --> MODEL
    MODEL --> XRAY
    MODEL --> CHECKIN
    MODEL --> ALERT
    XRAY --> ADVISOR

    MODEL -->|"state and event<br/>ws://192.168.77.2:8765/ws"| SCREEN
    XRAY -->|"state"| SCREEN
    HEALTH -->|"state"| SCREEN
    CHECKIN -->|"state and event"| SCREEN
    ALERT -->|"state and event"| SCREEN
    ADVISOR -->|"state and event"| SCREEN
    SERVE -->|"page and proof data"| SCREEN
    SCREEN -->|"cmd over the same WebSocket"| MODEL

    MODEL -->|"events"| NARRATOR
    NARRATOR -->|"narration<br/>127.0.0.1:5600"| BUS
    MODEL -->|"zone and alert state"| BRIDGE
    BRIDGE -->|"Arduino Router Bridge"| LED

    classDef source fill:#FAF7EF,stroke:#8F8A7E,color:#1C1B17;
    classDef core fill:#F4F0E6,stroke:#4F5E2E,color:#1C1B17;
    classDef output fill:#FAF7EF,stroke:#4F5E2E,color:#1C1B17;
    class PI_RADIO,WIFI,BLE,TEACHER,CAMWATCH source;
    class BUS,FEATURES,HEALTH,MODEL,XRAY,CHECKIN,ALERT,ADVISOR,NARRATOR core;
    class SCREEN,SERVE,BRIDGE,LED output;
```

## Inputs and bus

The UNO Q's Wi-Fi and Bluetooth readers send `rssi` messages to the local bus at `127.0.0.1:5600`. The Pi radio node sends its readings over the direct Ethernet cable to `192.168.77.2:5600`, while the App Lab camera teacher reaches the same bus through `msgpack-rpc-router:5600`. Camera state and setup labels use the same contract-v2 envelope as the radio data.

The bus listens on `UDP 0.0.0.0:5600`, adds board receive time, records sequence gaps, and forwards the agreed input stream to the brain at `UDP 127.0.0.1:5601`. Window joins and proof timing use that board receive time so every producer shares one clock at the decision boundary.

## Brain and advisor

The brain builds signal windows, checks link health, and runs the trained person, object, zone, and motion model. It also produces the radio X-ray, applies the check-in and no-movement alert rules, and contains the router advisor. The advisor reads persistent radio change and contract-defined router spots; it does not bypass the brain or run on the Pi.

If a required classifier link is blind, the brain sends a blind health state and no prediction. The screen must not translate missing or unhealthy input into an empty room.

## Screen, narration, and LED grid

The brain publishes contract-v2 `state` and `event` messages on `ws://192.168.77.2:8765/ws`. The Pi-driven browser loads the page and proof data from `http://192.168.77.2:8080`, renders the live state, and sends commands back over the WebSocket.

Brain events also feed the on-board narrator. The narrator returns a `narration` message to the local bus at `127.0.0.1:5600`, so generated and template explanations rejoin the same ordered state path.

For the physical display, the board host calls the `arduino` Bridge package with zone and alert state. The Arduino Router Bridge carries that small command to the UNO Q microcontroller, which draws it on the LED grid; the Pi is not in that path.

## Privacy and deployment boundaries

- All trained models and learned decisions run on the UNO Q's Dragonwing CPU.
- The camera teacher is for setup labels only and saves no image or video.
- The Pi provides network, radio, and display functions and runs no model.
- Runtime services bind only to the local addresses defined in `CONTRACTS.md`; the system uses its own network, not venue Wi-Fi or a cloud service.
