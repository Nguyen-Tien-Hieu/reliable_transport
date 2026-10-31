
import argparse
import socket
import sys

from utils import PacketHeader, compute_checksum

HEADER_SIZE = 16


def create_packet(packet_type, seq_num, payload=b""):
    header = PacketHeader(
        type=packet_type,
        seq_num=seq_num,
        length=len(payload),
        checksum=0
    )
    header.checksum = compute_checksum(header / payload)
    return bytes(header / payload)


def receiver(receiver_ip, receiver_port, window_size):
    if window_size <= 0:
        raise ValueError("Window size must be greater than 0")

    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    s.bind((receiver_ip, receiver_port))

    expected_seq = 1
    received_data = {}
    active = False

    print("RTP-opt Receiver is waiting for START...", file=sys.stderr)

    try:
        while True:
            pkt, address = s.recvfrom(2048)

            if len(pkt) < HEADER_SIZE:
                continue

            header = PacketHeader(pkt[:HEADER_SIZE])

            if len(pkt) != HEADER_SIZE + header.length:
                continue

            payload = pkt[HEADER_SIZE:]

            received_checksum = header.checksum
            header.checksum = 0

            if received_checksum != compute_checksum(header / payload):
                continue

            # START packet
            if header.type == 0 and header.seq_num == 0:
                if not active:
                    active = True
                    expected_seq = 1
                    received_data = {}

                # Always resend ACK for START
                ack = create_packet(3, 1)
                s.sendto(ack, address)

                print("Received START, sent ACK 1", file=sys.stderr)

            # DATA packet
            elif header.type == 2 and active:
                seq = header.seq_num

                if seq < expected_seq:
                    # Duplicate DATA: send ACK again
                    ack = create_packet(3, seq)
                    s.sendto(ack, address)

                elif expected_seq <= seq < expected_seq + window_size:
                    if seq not in received_data:
                        received_data[seq] = payload

                    # Individual ACK: ACK number equals DATA sequence
                    ack = create_packet(3, seq)
                    s.sendto(ack, address)

                    print(f"Received DATA {seq}, sent ACK {seq}", file=sys.stderr)

                    # Write data in the correct order
                    while expected_seq in received_data:
                        sys.stdout.buffer.write(received_data[expected_seq])
                        del received_data[expected_seq]
                        expected_seq += 1

                    sys.stdout.buffer.flush()

            # END packet
            elif header.type == 1 and active:
                if header.seq_num == expected_seq:
                    ack = create_packet(3, header.seq_num + 1)
                    s.sendto(ack, address)

                    print("Received END, sent END ACK", file=sys.stderr)
                    break

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

    receiver(args.receiver_ip, args.receiver_port, args.window_size)


if __name__ == "__main__":
    main()
