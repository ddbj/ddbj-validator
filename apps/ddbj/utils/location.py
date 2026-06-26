from Bio.SeqFeature import CompoundLocation

def get_introns_from_join(feature):
    """
    CompoundLocation (join) を持つフィーチャーから、
    各イントロンの (start, end, length) を辞書のリストとして返す。
    プロセス間通信(JSON/pickle)のため、BiopythonのPositionオブジェクトは純粋なintに変換する。
    """
    introns = []
    if not isinstance(feature.location, CompoundLocation):
        return introns

    parts = feature.location.parts
    for i in range(len(parts) - 1):
        exon1 = parts[i]
        exon2 = parts[i+1]

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