
import argparse
import socket
import sys

from utils import PacketHeader, compute_checksum


HEADER_SIZE = 16


# Tao packet ACK
def create_packet(packet_type, seq_num, payload=b""):
    header = PacketHeader(
        type=packet_type,
        seq_num=seq_num,
        length=len(payload),
        checksum=0
    )

    header.checksum = compute_checksum(header / payload)

    return bytes(header / payload)


# Receiver
def receiver(receiver_ip, receiver_port, window_size):
    if window_size <= 0:
        raise ValueError("Window size must be greater than 0")

    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    s.bind((receiver_ip, receiver_port))

    expected_seq = 1
    received_data = {}

    active = False

    print("Receiver is waiting for START...", file=sys.stderr)

    try:
        while True:
            pkt, address = s.recvfrom(2048)

            # Kiem tra kich thuoc packet
            if len(pkt) < HEADER_SIZE:
                continue

            header = PacketHeader(pkt[:HEADER_SIZE])

            # Kiem tra do dai payload
            if len(pkt) != HEADER_SIZE + header.length:
                continue

            payload = pkt[HEADER_SIZE:]

            # Kiem tra checksum
            received_checksum = header.checksum
            header.checksum = 0

            if received_checksum != compute_checksum(header / payload):
                continue

            # Nhan START
            if header.type == 0 and header.seq_num == 0:

                # Neu dang nhan du lieu thi bo qua START
                if active:
                    continue

                active = True
                expected_seq = 1
                received_data = {}

                print("Received START", file=sys.stderr)

                ack_packet = create_packet(3, 1)
                s.sendto(ack_packet, address)

                print("Sent ACK for START", file=sys.stderr)

            # Nhan DATA
            elif header.type == 2 and active:

                seq = header.seq_num

                # Chi nhan cac goi nam trong cua so
                if expected_seq <= seq < expected_seq + window_size:

                    if seq not in received_data:
                        received_data[seq] = payload

                    # Tim cac goi lien tiep da nhan du
                    while expected_seq in received_data:
                        expected_seq += 1

                # Gui ACK tich luy
                ack_packet = create_packet(3, expected_seq)
                s.sendto(ack_packet, address)

                print("Received DATA:", seq, file=sys.stderr)
                print("Sent ACK:", expected_seq, file=sys.stderr)

            # Nhan END
            elif header.type == 1 and active:

                if header.seq_num == expected_seq:

                    # Ghi du lieu theo dung thu tu
                    for seq in range(1, expected_seq):
                        if seq in received_data:
                            sys.stdout.buffer.write(received_data[seq])

                    sys.stdout.buffer.flush()

                    # Gui ACK cho END
                    ack_packet = create_packet(3, header.seq_num + 1)
                    s.sendto(ack_packet, address)

                    print("Received END", file=sys.stderr)
                    print("Sent ACK for END", file=sys.stderr)

                    break

    finally:
        s.close()


def main():
    parser = argparse.ArgumentParser()

    parser.add_argument("receiver_ip")
    parser.add_argument("receiver_port", type=int)
    parser.add_argument("window_size", type=int)

    args = parser.parse_args()

    receiver(args.receiver_ip, args.receiver_port, args.window_size)


if __name__ == "__main__":
    main()
