
import argparse
import socket
import sys
import time

from utils import PacketHeader, compute_checksum


# Kich thuoc toi da cua mot packet
MAX_PACKET_SIZE = 1472

# Header co 4 truong IntField, moi truong 4 byte
HEADER_SIZE = 16

# Kich thuoc payload toi da
MAX_PAYLOAD_SIZE = MAX_PACKET_SIZE - HEADER_SIZE

# Thoi gian cho ACK: 500 ms
TIMEOUT = 0.5


# Doc du lieu tu stdin va chia thanh cac packet
def read_data():
    data = sys.stdin.buffer.read()

    packets = []

    for i in range(0, len(data), MAX_PAYLOAD_SIZE):
        chunk = data[i:i + MAX_PAYLOAD_SIZE]
        packets.append(chunk)

    return packets


# Tao mot packet voi header va payload
def create_packet(packet_type, seq_num, payload=b""):
    header = PacketHeader(
        type=packet_type,
        seq_num=seq_num,
        length=len(payload),
        checksum=0
    )

    header.checksum = compute_checksum(header / payload)

    packet = header / payload

    return bytes(packet)


# Kiem tra ACK va cho ACK co seq_num mong doi
def wait_for_ack(s, expected_seq, timeout=TIMEOUT):
    start_time = time.monotonic()

    while time.monotonic() - start_time < timeout:
        remaining = timeout - (time.monotonic() - start_time)
        s.settimeout(max(remaining, 0.001))

        try:
            pkt, address = s.recvfrom(2048)
        except socket.timeout:
            return False

        if len(pkt) < HEADER_SIZE:
            continue

        header = PacketHeader(pkt[:HEADER_SIZE])

        if header.type != 3:
            continue

        received_checksum = header.checksum
        header.checksum = 0

        payload = pkt[HEADER_SIZE:HEADER_SIZE + header.length]

        if received_checksum != compute_checksum(header / payload):
            continue

        if header.seq_num == expected_seq:
            return True

    return False


# Gui START va cho ACK
def send_start(s, receiver_ip, receiver_port):
    start_packet = create_packet(0, 0)

    while True:
        s.sendto(start_packet, (receiver_ip, receiver_port))

        if wait_for_ack(s, 1):
            print("START acknowledged", file=sys.stderr)
            return

        print("START timeout, retransmitting...", file=sys.stderr)


# Nhan va kiem tra mot ACK
def receive_ack(s):
    try:
        pkt, address = s.recvfrom(2048)
    except socket.timeout:
        return None

    if len(pkt) < HEADER_SIZE:
        return None

    header = PacketHeader(pkt[:HEADER_SIZE])

    payload = pkt[HEADER_SIZE:HEADER_SIZE + header.length]

    received_checksum = header.checksum
    header.checksum = 0

    if received_checksum != compute_checksum(header / payload):
        return None

    if header.type != 3:
        return None

    return header.seq_num


# Tao cac DATA packet voi seq_num bat dau tu 1
def create_data_packets(packets):
    data_packets = {}

    for seq_num, payload in enumerate(packets, start=1):
        data_packets[seq_num] = create_packet(2, seq_num, payload)

    return data_packets


# Gui tat ca DATA packet theo co che cua so truot
def send_data(s, receiver_ip, receiver_port, packets, window_size):
    data_packets = create_data_packets(packets)

    total_packets = len(data_packets)

    # base: goi DATA dau tien chua duoc ACK
    base = 1

    # next_seq: so thu tu goi tiep theo can gui
    next_seq = 1

    timer_start = None

    while base <= total_packets:

        # Gui cac goi trong cua so
        while next_seq <= total_packets and next_seq < base + window_size:

            s.sendto(data_packets[next_seq], (receiver_ip, receiver_port))

            print("Sent DATA:", next_seq, file=sys.stderr)

            if base == next_seq:
                timer_start = time.monotonic()

            next_seq += 1

        # Tinh thoi gian con lai cua bo dem
        remaining = TIMEOUT - (time.monotonic() - timer_start)

        if remaining <= 0:
            ack = None
        else:
            s.settimeout(remaining)
            ack = receive_ack(s)

        # Neu nhan duoc ACK hop le
        if ack is not None:

            # ACK tich luy: ack la goi tiep theo receiver dang cho
            if base < ack <= next_seq:

                print("Received ACK:", ack, file=sys.stderr)

                base = ack

                # Reset timer khi cua so tien len
                if base < next_seq:
                    timer_start = time.monotonic()
                else:
                    timer_start = None

        # Neu het 500ms ma cua so chua tien len
        if timer_start is not None:
            if time.monotonic() - timer_start >= TIMEOUT:

                print("Timeout! Retransmitting window", file=sys.stderr)

                # Gui lai tat ca cac goi chua duoc ACK
                for seq_num in range(base, next_seq):
                    s.sendto(
                        data_packets[seq_num],
                        (receiver_ip, receiver_port)
                    )

                    print("Retransmitted DATA:", seq_num, file=sys.stderr)

                timer_start = time.monotonic()


# Gui END va cho ACK cua END
def send_end(s, receiver_ip, receiver_port, total_packets):
    end_seq = total_packets + 1

    end_packet = create_packet(1, end_seq)

    while True:
        s.sendto(end_packet, (receiver_ip, receiver_port))

        print("Sent END:", end_seq, file=sys.stderr)

        if wait_for_ack(s, end_seq + 1):
            print("END acknowledged", file=sys.stderr)
            return

        print("END timeout, retransmitting...", file=sys.stderr)


# Chuong trinh Sender
def sender(receiver_ip, receiver_port, window_size):
    if window_size <= 0:
        raise ValueError("Window size must be greater than 0")

    packets = read_data()

    print("Number of DATA packets:", len(packets), file=sys.stderr)

    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)

    try:
        # Buoc 1: Bat dau ket noi
        send_start(s, receiver_ip, receiver_port)

        # Buoc 2: Gui DATA
        send_data(
            s,
            receiver_ip,
            receiver_port,
            packets,
            window_size
        )

        # Buoc 3: Gui END
        send_end(
            s,
            receiver_ip,
            receiver_port,
            len(packets)
        )

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
