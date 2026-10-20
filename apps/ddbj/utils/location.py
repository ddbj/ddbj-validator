from Bio.SeqFeature import CompoundLocation


def is_origin_junction(part_a, part_b, seq_len):
    """parts 上で隣り合う 2 part の継ぎ目が、circular 配列の origin（全長 L → 1）を跨ぐか。

    登録者は plus でも minus でも `join(n..L,1..m)` / `complement(join(n..L,1..m))` と書く。
    parser は minus 鎖の parts を逆順（[1..m, n..L]）に並べるので、鎖で見る向きを変える。
    向きを問わず両方を見ると `join(1..10,50..L)` のような普通の join を誤って跨ぎと判定するため、
    必ず鎖ごとに片方向だけを見る。座標は Biopython の 0-based（start 0 = 1 塩基目、end L = L 塩基目）。
    """
    if not seq_len:
        return False
    if part_a.strand == -1:
        return int(part_a.start) == 0 and int(part_b.end) == seq_len
    return int(part_a.end) == seq_len and int(part_b.start) == 0


def crosses_origin(location, seq_len):
    """location（join）が origin を跨ぐ継ぎ目を含むか。"""
    if not isinstance(location, CompoundLocation):
        return False
    parts = location.parts
    return any(is_origin_junction(parts[i], parts[i + 1], seq_len) for i in range(len(parts) - 1))


def circular_entry_ids(records):
    """`TOPOLOGY circular` が付いたエントリ ID の集合。COMMON に付いていれば全エントリ。"""
    def _is_circular(record):
        return any(f.type == "TOPOLOGY" and "circular" in f.qualifiers for f in record.features)

    common = records.get("COMMON")
    if common is not None and _is_circular(common):
        return {k for k in records if k != "COMMON"}
    return {k for k, r in records.items() if k != "COMMON" and _is_circular(r)}


def get_introns_from_join(feature, seq_len=None):
    """
    CompoundLocation (join) を持つフィーチャーから、
    各イントロンの (start, end, length) を辞書のリストとして返す。
    プロセス間通信(JSON/pickle)のため、BiopythonのPositionオブジェクトは純粋なintに変換する。

    seq_len を渡すと、circular 配列の origin を跨ぐ継ぎ目（`join(n..L,1..m)`）は intron にしない
    （ゲノム上は連続している）。渡さないと m..n-1（ほぼ配列全体）を intron と誤認する。
    """
    introns = []
    if not isinstance(feature.location, CompoundLocation):
        return introns

    parts = feature.location.parts
    for i in range(len(parts) - 1):
        exon1 = parts[i]
        exon2 = parts[i+1]

        if is_origin_junction(exon1, exon2, seq_len):
            continue

        intron_start = exon1.end
        intron_end = exon2.start

        # エクソンの位置関係が逆転している（マイナス鎖などの）ケースの補正
        if intron_start >= intron_end:
            intron_start, intron_end = sorted([exon1.end, exon1.start, exon2.end, exon2.start])[1:3]

        start_val = int(intron_start)
        end_val = int(intron_end)

        introns.append({
            "start": start_val,
            "end": end_val,
            "length": end_val - start_val
        })

    return introns


def get_feature_positions(location):
    """
    フィーチャーの location が覆う 0-based の塩基位置を、parts 順・鎖の向きを考慮してリストで返す。
    マイナス鎖の part は末尾から先頭に向かって列挙する。location が None なら空リスト。
    """
    pos_list = []
    if not location:
        return pos_list
    for part in location.parts:
        start = int(part.start)
        end = int(part.end)
        strand = part.strand if part.strand is not None else 1
        if strand == -1:
            pos_list.extend(range(end - 1, start - 1, -1))
        else:
            pos_list.extend(range(start, end))
    return pos_list