/** Unit tests target pure TypeScript logic modules under src/ (API client,
 * version gate, progress sync, stream-URL recovery). They deliberately avoid
 * importing native modules so the suite runs fast and deterministically in
 * Node without an emulator. */
module.exports = {
  testEnvironment: "node",
  roots: ["<rootDir>/src"],
  testMatch: ["**/__tests__/**/*.test.ts"],
  moduleNameMapper: {
    "^@/(.*)$": "<rootDir>/src/$1",
  },
  clearMocks: true,
  transform: {
    "^.+\\.tsx?$": [
      "ts-jest",
      {
        tsconfig: {
          strict: true,
          esModuleInterop: true,
          skipLibCheck: true,
        },
      },
    ],
  },
};
