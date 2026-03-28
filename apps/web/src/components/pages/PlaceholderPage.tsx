/**
 * PlaceholderPage — generic placeholder for routes not yet implemented.
 */

interface PlaceholderPageProps {
  title: string;
  description: string;
}

export function PlaceholderPage({ title, description }: PlaceholderPageProps) {
  return (
    <div>
      <h1 className="mb-2 text-2xl font-bold text-gray-900 dark:text-white">
        {title}
      </h1>
      <p className="mb-8 text-sm text-gray-500 dark:text-gray-400">
        {description}
      </p>

      <div className="flex flex-col items-center justify-center rounded-lg border-2 border-dashed border-gray-300 bg-white py-16 dark:border-gray-600 dark:bg-gray-800">
        <svg
          className="mb-4 h-12 w-12 text-gray-400"
          fill="none"
          viewBox="0 0 24 24"
          stroke="currentColor"
          strokeWidth={1}
        >
          <path
            strokeLinecap="round"
            strokeLinejoin="round"
            d="M19.428 15.428a2 2 0 00-1.022-.547l-2.387-.477a6 6 0 00-3.86.517l-.318.158a6 6 0 01-3.86.517L6.05 15.21a2 2 0 00-1.806.547M8 4h8l-1 1v5.172a2 2 0 00.586 1.414l5 5c1.26 1.26.367 3.414-1.415 3.414H4.828c-1.782 0-2.674-2.154-1.414-3.414l5-5A2 2 0 009 10.172V5L8 4z"
          />
        </svg>
        <p className="text-lg font-medium text-gray-600 dark:text-gray-300">
          Coming Soon
        </p>
        <p className="mt-1 text-sm text-gray-400">
          This feature is under development.
        </p>
      </div>
    </div>
  );
}
