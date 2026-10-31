
import argparse
import socket
import sys
import time

from utils import PacketHeader, compute_checksum

HEADER_SIZE = 16
MAX_PACKET_SIZE = 1472
MAX_PAYLOAD_SIZE = MAX_PACKET_SIZE - HEADER_SIZE
TIMEOUT = 0.5


def create_packet(packet_type, seq_num, payload=b""):
    header = PacketHeader(
        type=packet_type,
        seq_num=seq_num,
        length=len(payload),
        checksum=0
    )
    header.checksum = compute_checksum(header / payload)
    return bytes(header / payload)


def receive_ack(s):
    try:
        pkt, address = s.recvfrom(2048)

        if len(pkt) < HEADER_SIZE:
            return None

        header = PacketHeader(pkt[:HEADER_SIZE])

        if len(pkt) != HEADER_SIZE + header.length:
            return None

        payload = pkt[HEADER_SIZE:]
        received_checksum = header.checksum
        header.checksum = 0

        if received_checksum != compute_checksum(header / payload):
            return None

        if header.type != 3:
            return None

        return header.seq_num

    except socket.timeout:
        return None


def send_control_packet(s, packet, expected_ack):
    while True:
        s.sendto(packet, s.getpeername())
        start_time = time.monotonic()

        while True:
            remaining = TIMEOUT - (time.monotonic() - start_time)

            if remaining <= 0:
                break

            s.settimeout(remaining)
            ack = receive_ack(s)

            if ack == expected_ack:
                return


def send_data(s, packets, window_size):
    total_packets = len(packets)

    base = 1
    next_seq = 1
    acknowledged = set()
    timer_start = None

    while base <= total_packets:

        # Send new packets within the window
        while next_seq <= total_packets and next_seq < base + window_size:
            s.send(packets[next_seq - 1])
            print(f"Sent DATA {next_seq}", file=sys.stderr)

            if timer_start is None:
                timer_start = time.monotonic()

            next_seq += 1

        # Wait for individual ACK
        remaining = TIMEOUT - (time.monotonic() - timer_start)

        if remaining > 0:
            s.settimeout(remaining)
            ack = receive_ack(s)
        else:
            ack = None

        # Process ACK
        if ack is not None and base <= ack < next_seq:
            acknowledged.add(ack)

            print(f"Received ACK {ack}", file=sys.stderr)

            old_base = base

            while base in acknowledged:
                base += 1

            # Window advances
            if base > old_base:
                timer_start = time.monotonic() if base < next_seq else None

        # Timeout: retransmit only unacknowledged packets
        elif ack is None:
            for seq in range(base, next_seq):
                if seq not in acknowledged:
                    s.send(packets[seq - 1])
                    print(f"Retransmitted DATA {seq}", file=sys.stderr)

            timer_start = time.monotonic()


def sender(receiver_ip, receiver_port, window_size):
    if window_size <= 0:
        raise ValueError("Window size must be greater than 0")

    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    s.connect((receiver_ip, receiver_port))

    try:
        # Read data from standard input
        data = sys.stdin.buffer.read()

        # Divide data into packets
        chunks = [
            data[i:i + MAX_PAYLOAD_SIZE]
            for i in range(0, len(data), MAX_PAYLOAD_SIZE)
        ]

        packets = [
            create_packet(2, seq, chunk)
            for seq, chunk in enumerate(chunks, start=1)
        ]

        # Send START
        start_packet = create_packet(0, 0)
        send_control_packet(s, start_packet, 1)

        print("START acknowledged", file=sys.stderr)

        # Send DATA packets
        send_data(s, packets, window_size)

        # Send END
        end_seq = len(packets) + 1
        end_packet = create_packet(1, end_seq)

        send_control_packet(s, end_packet, end_seq + 1)

        print("END acknowledged", file=sys.stderr)

    finally:
        s.close()


def main():
    parser = argparse.ArgumentParser()

    parser.add_argument(
        "receiver_ip",
        help="The IP address of the host that receiver is running on"
    )

    parser.add_argument(
        "receiver_port",
        type=int,
        help="The port number on which receiver is listening"
    )

    parser.add_argument(
        "window_size",
        type=int,
        help="Maximum number of outstanding packets"
    )

    args = parser.parse_args()

    sender(args.receiver_ip, args.receiver_port, args.window_size)


if __name__ == "__main__":
    main()
