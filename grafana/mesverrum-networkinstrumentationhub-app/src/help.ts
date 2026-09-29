export type HelpEntry = { title: string; body: string };

export const HELP: Record<string, HelpEntry> = {
  collector: {
    title: 'Why pick a collector?',
    body: 'The collector is the Alloy that will do the asking. It has to be on a machine that can reach the devices. If your networks cannot talk to each other, each one needs its own collector.',
  },
  alloy: {
    title: 'What is Alloy?',
    body: 'Alloy is the program that collects the data. It runs on a server you own, asks the switches how they are doing, and sends the answers to Grafana Cloud.',
  },
  fleet: {
    title: 'What is Fleet Management?',
    body: 'Fleet Management hands settings to your collectors. When you click Apply, the hub gives your settings to Fleet, and the collector you chose picks them up. You do not log in to the server.',
  },
  install: {
    title: 'Installing a new collector',
    body: 'Pick this when the devices are on a network none of your current collectors can reach. You run one command on a server inside that network. It starts the Network Alloy, which checks in with Fleet by the name you gave it. Once it shows up, this page lets you continue.',
  },
  credentials: {
    title: 'What is the credential file?',
    body: 'Devices only answer a collector that knows the password. That password stays in a file on the collector. The hub only sees the nickname of each login.',
  },
  authname: {
    title: 'What is an auth name?',
    body: 'The name of a login in the credential file on the collector, such as public_v2. This box is only that name. The password or community string stays in the file and is never typed here. Add every nickname that might work. Each address is tried in the order you list them, and the first one that answers is kept.',
  },
  group: {
    title: 'What is a group?',
    body: 'A group is a set of address ranges plus the login to try. The short name shows up on the metrics. The note is kept with the group so the next person knows why these devices are together.',
  },
  cidr: {
    title: 'What is a CIDR?',
    body: 'A short way to write a range of addresses. 172.20.20.0/24 means 172.20.20.1 through 172.20.20.254.',
  },
  importDevice: {
    title: 'What does Import mean?',
    body: 'Found means the device answered the discovery scan. The list is discovery_snmp_device_info for this group. The collector log does not list known devices, so this page reads the metric.',
  },
  whosends: {
    title: 'Alloy polls vs the device sends',
    body: 'Polling means the collector asks, and that starts after Apply. Alarms, logs, and traffic details mean the device has to be pointed at the collector. Those stay on Listening until the first message.',
  },
  neighbors: {
    title: 'Neighbor topology',
    body: 'Switches can say what is plugged into each port. That is what draws device-to-device links. The collector asks for it, the same way it asks for health.',
  },
  rescan: {
    title: 'Look for new devices',
    body: 'Daily re-checks the ranges every 24 hours. Run once checks them when you apply, then waits about a year. Both are the discovery.snmp setting refresh_interval. Change that value in the collector config later if you want a different schedule.',
  },
  basics: {
    title: 'What is always collected',
    body: 'Every minute: is the device up, processor and memory, traffic on each port, and whether each port is up. Every five minutes: port names, error counts, and the addresses on the device. Dashboards and alerts need both, so there is no switch for them.',
  },
  ports: {
    title: 'Why these port numbers?',
    body: 'The traditional ports are 162 and 514. A normal user account cannot listen below 1024, and Alloy should not run as an administrator. This collector listens on 11621 for alarms, 1516 for logs, 2056 for NetFlow and IPFIX, and 6345 for sFlow. Those sit one step off the lab collector, which already holds 1620, 1514, 2055, and 6344 on the same host. When you point the device, include that port.',
  },
  traps: {
    title: 'SNMP traps',
    body: 'A trap is an alarm the device sends the moment something happens, like a port going down. Apply turns the listener on at UDP 11621. Someone still has to point the device at it.',
  },
  syslog: {
    title: 'Syslog',
    body: 'The running log the device keeps. Apply turns the listener on at UDP 1516. The device has to be told to send there.',
  },
  netflow: {
    title: 'NetFlow and IPFIX',
    body: 'These are three ways to say who talked to whom. One listener understands all three, on UDP 2056. Not every device sends them, and it is more data than the other options, so it starts off. Apply is what turns the listener on.',
  },
  sflow: {
    title: 'sFlow',
    body: 'sFlow answers the same question, but the collector cannot read it on the NetFlow port. It is a separate listener on UDP 6345. The usual port is 6343, and the lab Alloy already uses 6344.',
  },
  apply: {
    title: 'What happens when I click Apply?',
    body: 'The hub writes this group into Fleet for the one collector you picked. That collector picks it up within a minute or two and starts polling. No other collector is changed.',
  },
  listening: {
    title: 'Why does it say Listening?',
    body: 'The collector is ready and nothing has arrived yet. That is normal for alarms, logs, and traffic details until the device is pointed at it. It is not an error.',
  },
  deviceapp: {
    title: 'Where are the devices?',
    body: 'Device management is its own app. This wizard links you there after Apply. You come back to that app to open a device. The wizard is only for setting up a collector and a group.',
  },
};
