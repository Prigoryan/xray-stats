reduce .stat[] as $item ({};
    if $item.name | startswith("user>>>") then
        ($item.name | split(">>>")) as $keys
        | .[$keys[1]] |= (if . == null then [0, 0] else . end)
        |
            if $keys[3] == "downlink" then
                .[$keys[1]][0] += ($item.value // 0 | tonumber)
            elif $keys[3] == "uplink" then
                .[$keys[1]][1] += ($item.value // 0 | tonumber)
            else
                .
            end
    else
        .
    end
)
    | to_entries
    | sort_by(-.value[0] // 0)[]
    | "\(.key)\t\(.value[0])\t\(.value[1])"
