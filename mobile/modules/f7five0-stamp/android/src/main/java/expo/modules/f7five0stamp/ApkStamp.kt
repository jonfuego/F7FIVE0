package expo.modules.f7five0stamp

import java.io.File
import java.io.RandomAccessFile
import java.nio.ByteBuffer
import java.nio.ByteOrder

/**
 * Reads the server stamp from an APK's signing block.
 *
 * The server adds one ID-value pair (ID 0x46374635, "F7F5") to the APK
 * Signing Block when it hands the app out (backend/app/services/apk_stamp.py).
 * The value is UTF-8 JSON, e.g. {"v":1,"servers":["https://media.example.com"]}.
 * Android keeps the installed APK byte for byte, so the app can read it back
 * from its own base.apk. Returns null for an unstamped APK or anything that
 * does not parse; this must never crash the app.
 */
object ApkStamp {
  const val STAMP_ID = 0x46374635
  private const val EOCD_SIG = 0x06054b50
  private const val MAX_VALUE = 8192
  private val MAGIC = "APK Sig Block 42".toByteArray(Charsets.US_ASCII)

  fun read(path: String): String? = try {
    RandomAccessFile(File(path), "r").use { readFrom(it) }
  } catch (e: Exception) {
    null
  }

  private fun readAt(f: RandomAccessFile, pos: Long, len: Int): ByteBuffer {
    val buf = ByteArray(len)
    f.seek(pos)
    f.readFully(buf)
    return ByteBuffer.wrap(buf).order(ByteOrder.LITTLE_ENDIAN)
  }

  private fun readFrom(f: RandomAccessFile): String? {
    val size = f.length()
    if (size < 22) return null
    val tailLen = minOf(size, 22L + 0xFFFF).toInt()
    val tail = readAt(f, size - tailLen, tailLen)
    var eocd = -1
    for (i in tailLen - 22 downTo 0) {
      if (tail.getInt(i) == EOCD_SIG) {
        val commentLen = tail.getShort(i + 20).toInt() and 0xFFFF
        if (i + 22 + commentLen == tailLen) { eocd = i; break }
      }
    }
    if (eocd < 0) return null
    val cdOffset = tail.getInt(eocd + 16).toLong() and 0xFFFFFFFFL
    if (cdOffset < 32 || cdOffset > size) return null
    val footer = readAt(f, cdOffset - 24, 24)
    val magic = ByteArray(16)
    footer.position(8); footer.get(magic)
    if (!magic.contentEquals(MAGIC)) return null
    val blockSize = footer.getLong(0)
    if (blockSize < 24 || blockSize > cdOffset - 8 || blockSize > 16L * 1024 * 1024) return null
    val blockStart = cdOffset - blockSize - 8
    val block = readAt(f, blockStart + 8, (blockSize - 24).toInt()) // the pairs only
    while (block.remaining() >= 12) {
      val len = block.getLong()
      if (len < 4 || len > block.remaining()) return null
      val id = block.getInt()
      val valueLen = (len - 4).toInt()
      if (id == STAMP_ID) {
        if (valueLen > MAX_VALUE) return null
        val value = ByteArray(valueLen)
        block.get(value)
        return String(value, Charsets.UTF_8)
      }
      block.position(block.position() + valueLen)
    }
    return null
  }
}
