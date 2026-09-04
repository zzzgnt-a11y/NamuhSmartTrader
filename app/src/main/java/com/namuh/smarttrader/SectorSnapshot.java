package com.namuh.smarttrader;

public class SectorSnapshot {
    public String sector;
    public Double changePct;
    public Double turnoverScore;
    public String leader;
    public boolean realtime;

    public SectorSnapshot(String sector, Double changePct, Double turnoverScore, String leader, boolean realtime) {
        this.sector = sector;
        this.changePct = changePct;
        this.turnoverScore = turnoverScore;
        this.leader = leader;
        this.realtime = realtime;
    }
}
