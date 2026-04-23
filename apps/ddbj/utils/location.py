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