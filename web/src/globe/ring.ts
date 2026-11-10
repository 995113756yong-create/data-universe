// 固定容量环形缓冲区的下标管理（纯逻辑，便于测试）
export class RingIndex {
  private next = 0;
  private filled = 0;
  constructor(readonly capacity: number) {
    if (capacity <= 0) throw new Error("capacity must be > 0");
  }
  /** 申请一个槽位；满了覆盖最旧的 */
  take(): number {
    const i = this.next;
    this.next = (this.next + 1) % this.capacity;
    if (this.filled < this.capacity) this.filled++;
    return i;
  }
  get size() {
    return this.filled;
  }
}
